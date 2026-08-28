from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "submissions.json"
README = ROOT / "README.md"
DASHBOARD_SVG = ROOT / "assets" / "dashboard.svg"

PLATFORM_COLORS = {
    "LeetCode": ("#ff7a18", "#ff4d4d"),
    "CodeChef": ("#a855f7", "#6d28d9"),
    "HackerRank": ("#34d399", "#059669"),
}


def load_records() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}


def display_language(value: str | None) -> str:
    """Normalize platform-specific Python runtime names for the dashboard."""
    v = (value or "Unknown").strip().lower()
    if v in {"pypy3", "pypy 3", "pypy"} or "python" in v:
        return "Python"
    return value or "Unknown"


def unique_records(records: dict) -> list[dict]:
    """Count one solved problem once per platform/language."""
    unique = {}
    for record in records.values():
        language = display_language(record.get("language"))
        key = (
            record.get("platform"),
            record.get("problem_id") or record.get("slug") or record.get("title"),
            language.lower(),
        )
        normalized = dict(record)
        normalized["language"] = language
        unique[key] = normalized
    return list(unique.values())


def parse_date(record: dict):
    value = record.get("accepted_at") or record.get("acceptedAt")
    if not value:
        return None
    try:
        if str(value).isdigit():
            return datetime.fromtimestamp(int(value), tz=timezone.utc).date()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (ValueError, TypeError, OverflowError):
        return None


def streaks(records: list[dict]) -> tuple[int, int]:
    dates = sorted({d for r in records if (d := parse_date(r)) is not None})
    if not dates:
        return 0, 0

    best = current = 1
    for a, b in zip(dates, dates[1:]):
        if (b - a).days == 1:
            current += 1
            best = max(best, current)
        else:
            current = 1

    from datetime import date, timedelta
    today = date.today()
    current_streak = 0
    if dates[-1] in {today, today - timedelta(days=1)}:
        current_streak = 1
        i = len(dates) - 1
        while i > 0 and (dates[i] - dates[i - 1]).days == 1:
            current_streak += 1
            i -= 1
    return current_streak, best


def difficulty_counts(rows: list[dict]) -> Counter:
    return Counter(r.get("difficulty") for r in rows)


def platform_details(rows: list[dict]) -> tuple[Counter, Counter]:
    languages = Counter(r.get("language") or "Unknown" for r in rows)
    topics = Counter((r.get("tags") or ["Other"])[0] for r in rows)
    return languages, topics


def esc(value: str) -> str:
    return html.escape(str(value), quote=True)


def write_dashboard_svg(platform_rows: dict[str, list[dict]], total: int, current: int, best: int, overall_difficulty: Counter) -> None:
    """Generate a polished fixed-size SVG dashboard independent of GitHub README CSS."""
    width = 1100
    height = 1030
    card_x = 50
    card_w = 1000
    card_h = 220
    gap = 24

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs>',
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#080b12"/><stop offset="1" stop-color="#111827"/></linearGradient>',
        '<linearGradient id="summary" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#111827"/><stop offset="1" stop-color="#171d2b"/></linearGradient>',
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="#000000" flood-opacity="0.28"/></filter>',
        '<style>.title{font-family:Arial,Helvetica,sans-serif;fill:#f8fafc;font-weight:700}.muted{font-family:Arial,Helvetica,sans-serif;fill:#94a3b8}.body{font-family:Arial,Helvetica,sans-serif;fill:#e2e8f0}</style>',
        '</defs>',
        '<rect width="100%" height="100%" rx="22" fill="url(#bg)"/>',
        '<rect x="22" y="22" width="1056" height="986" rx="20" fill="none" stroke="#263043"/>',
        '<text x="550" y="72" text-anchor="middle" class="muted" font-size="16" letter-spacing="4">DSA PROGRESS</text>',
        '<text x="550" y="118" text-anchor="middle" class="title" font-size="38">Keep coding. Keep growing. 🚀</text>',
        f'<text x="550" y="171" text-anchor="middle" class="title" font-size="54">{total} <tspan fill="#94a3b8" font-size="30">problems solved</tspan></text>',
        '<rect x="95" y="198" width="910" height="76" rx="14" fill="url(#summary)" stroke="#2b3547"/>',
        f'<text x="200" y="245" text-anchor="middle" font-family="Arial" font-size="19" font-weight="700" fill="#4ade80">Easy {overall_difficulty["Easy"]}</text>',
        f'<text x="430" y="245" text-anchor="middle" font-family="Arial" font-size="19" font-weight="700" fill="#facc15">Medium {overall_difficulty["Medium"]}</text>',
        f'<text x="650" y="245" text-anchor="middle" font-family="Arial" font-size="19" font-weight="700" fill="#f87171">Hard {overall_difficulty["Hard"]}</text>',
        f'<text x="875" y="245" text-anchor="middle" font-family="Arial" font-size="19" font-weight="700" fill="#38bdf8">Unknown {overall_difficulty["Unknown"]}</text>',
        '<line x1="325" y1="218" x2="325" y2="254" stroke="#334155"/><line x1="540" y1="218" x2="540" y2="254" stroke="#334155"/><line x1="760" y1="218" x2="760" y2="254" stroke="#334155"/>',
        '<rect x="235" y="292" width="300" height="72" rx="14" fill="#111827" stroke="#263043"/>',
        '<text x="265" y="323" font-size="20">🔥</text><text x="300" y="320" class="muted" font-size="14">CURRENT STREAK</text>',
        f'<text x="300" y="348" class="title" font-size="23">{current} day{"s" if current != 1 else ""}</text>',
        '<rect x="565" y="292" width="300" height="72" rx="14" fill="#111827" stroke="#263043"/>',
        '<text x="595" y="323" font-size="20">🏆</text><text x="630" y="320" class="muted" font-size="14">BEST STREAK</text>',
        f'<text x="630" y="348" class="title" font-size="23">{best} day{"s" if best != 1 else ""}</text>',
        '<text x="550" y="414" text-anchor="middle" class="muted" font-size="15" letter-spacing="3">PLATFORMS</text>',
        '<line x1="80" y1="414" x2="350" y2="414" stroke="#263043"/><line x1="750" y1="414" x2="1020" y2="414" stroke="#263043"/>',
    ]

    for index, platform in enumerate(("LeetCode", "CodeChef", "HackerRank")):
        rows = platform_rows[platform]
        y = 438 + index * (card_h + gap)
        primary, secondary = PLATFORM_COLORS[platform]
        languages, topics = platform_details(rows)
        d = difficulty_counts(rows)
        lang_text = " · ".join(f"{k}: {v}" for k, v in languages.most_common()) or "—"
        topic_text = " · ".join(f"{k}: {v}" for k, v in topics.most_common(3)) or "—"

        parts.extend([
            f'<rect x="{card_x}" y="{y}" width="{card_w}" height="{card_h}" rx="18" fill="#0d1117" stroke="{primary}" stroke-opacity="0.75" filter="url(#shadow)"/>',
            f'<rect x="{card_x + 1}" y="{y + 1}" width="7" height="{card_h - 2}" rx="4" fill="{primary}"/>',
            f'<rect x="{card_x + 38}" y="{y + 38}" width="64" height="64" rx="16" fill="{primary}"/>',
            f'<text x="{card_x + 70}" y="{y + 79}" text-anchor="middle" font-family="Arial" font-size="32" font-weight="700" fill="#ffffff">{platform[0]}</text>',
            f'<text x="{card_x + 125}" y="{y + 68}" class="title" font-size="29">{esc(platform)}</text>',
            f'<rect x="{card_x + 805}" y="{y + 40}" width="145" height="52" rx="13" fill="{secondary}" fill-opacity="0.28" stroke="{primary}" stroke-opacity="0.7"/>',
            f'<text x="{card_x + 877}" y="{y + 63}" text-anchor="middle" class="muted" font-size="12">SOLVED</text>',
            f'<text x="{card_x + 877}" y="{y + 84}" text-anchor="middle" class="title" font-size="20">{len(rows)}</text>',
            f'<line x1="{card_x + 125}" y1="{y + 112}" x2="{card_x + 950}" y2="{y + 112}" stroke="#263043"/>',
            f'<text x="{card_x + 125}" y="{y + 141}" font-family="Arial" font-size="15" font-weight="700" fill="#4ade80">Easy {d["Easy"]}</text>',
            f'<text x="{card_x + 285}" y="{y + 141}" font-family="Arial" font-size="15" font-weight="700" fill="#facc15">Medium {d["Medium"]}</text>',
            f'<text x="{card_x + 465}" y="{y + 141}" font-family="Arial" font-size="15" font-weight="700" fill="#f87171">Hard {d["Hard"]}</text>',
            f'<text x="{card_x + 620}" y="{y + 141}" font-family="Arial" font-size="15" font-weight="700" fill="#38bdf8">Unknown {d["Unknown"]}</text>',
            f'<text x="{card_x + 125}" y="{y + 177}" class="body" font-size="14">⌘  Languages: {esc(lang_text)}</text>',
            f'<text x="{card_x + 600}" y="{y + 177}" class="body" font-size="14">◇  Topics: {esc(topic_text)}</text>',
        ])

    parts.extend([
        '<text x="550" y="1000" text-anchor="middle" class="muted" font-size="13">Automatically generated from accepted submissions</text>',
        '</svg>',
    ])

    DASHBOARD_SVG.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_SVG.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    raw_records = load_records()
    rows = unique_records(raw_records)
    difficulties = difficulty_counts(rows)
    current, best = streaks(rows)
    platform_rows = {
        platform: [r for r in rows if r.get("platform") == platform]
        for platform in ("LeetCode", "CodeChef", "HackerRank")
    }

    write_dashboard_svg(platform_rows, len(rows), current, best, difficulties)

    lines = [
        "# DSA Solutions",
        "",
        "Automated accepted-submission archive for LeetCode, CodeChef and HackerRank.",
        "",
        "## 📊 Progress Dashboard",
        "",
        f"<h2 align=\"center\">Total Progress — {len(rows)} problems solved</h2>",
        "",
        f"<p align=\"center\"><b>Easy {difficulties['Easy']} · Medium {difficulties['Medium']} · Hard {difficulties['Hard']}" + (f" · Unknown {difficulties['Unknown']}" if difficulties["Unknown"] else "") + "</b></p>",
        "",
        f"<p align=\"center\">🔥 Current streak: <b>{current} day{'s' if current != 1 else ''}</b> &nbsp;&nbsp; 🏆 Best streak: <b>{best} day{'s' if best != 1 else ''}</b></p>",
        "",
        "<h2 align=\"center\">Platforms</h2>",
        "",
        '<p align="center"><img src="assets/dashboard.svg" alt="DSA platform progress dashboard" width="100%"></p>',
        "",
        "---",
        "",
        "## 📁 Repository Layout",
        "`Platform / Language / Topic / Difficulty / Problem.cpp`",
        "",
        "_This dashboard is automatically regenerated after every sync._",
        "",
    ]

    README.write_text("\n".join(lines), encoding="utf-8")
    print(f"Dashboard updated: {len(rows)} unique solved problems")


if __name__ == "__main__":
    main()
