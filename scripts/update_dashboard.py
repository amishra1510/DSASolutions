from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "submissions.json"
README = ROOT / "README.md"
DASHBOARD_SVG = ROOT / "assets" / "dashboard.svg"
LOGO_DIR = ROOT / "assets" / "logos"

PLATFORM_COLORS = {
    "LeetCode": ("#ff7a18", "#ff4d4d"),
    "CodeChef": ("#a855f7", "#6d28d9"),
    "HackerRank": ("#34d399", "#059669"),
}
PLATFORM_LOGOS = {
    "LeetCode": "leetcode.svg",
    "CodeChef": "codechef.svg",
    "HackerRank": "hackerrank.svg",
}


def load_records() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}


def display_language(value: str | None) -> str:
    v = (value or "Unknown").strip().lower()
    if v in {"pypy3", "pypy 3", "pypy"} or "python" in v:
        return "Python"
    return value or "Unknown"


def unique_records(records: dict) -> list[dict]:
    unique = {}
    for record in records.values():
        language = display_language(record.get("language"))
        key = (record.get("platform"), record.get("problem_id") or record.get("slug") or record.get("title"), language.lower())
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


def counts(rows: list[dict]) -> Counter:
    return Counter(r.get("difficulty") for r in rows)


def details(rows: list[dict]) -> tuple[Counter, Counter]:
    return Counter(r.get("language") or "Unknown" for r in rows), Counter((r.get("tags") or ["Other"])[0] for r in rows)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def logo_markup(platform: str, x: int, y: int, size: int = 64) -> str:
    logo_path = LOGO_DIR / PLATFORM_LOGOS[platform]
    if not logo_path.exists():
        raise FileNotFoundError(f"Missing platform logo: {logo_path}")
    source = logo_path.read_text(encoding="utf-8")
    match = re.search(r'<path\b[^>]*\bd="([^"]+)"', source)
    if not match:
        raise ValueError(f"Could not find logo path in {logo_path}")
    return (
        f'<svg x="{x}" y="{y}" width="{size}" height="{size}" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-label="{esc(platform)} logo">'
        f'<path fill="#ffffff" d="{esc(match.group(1))}"/></svg>'
    )


def write_dashboard_svg(platform_rows, total, current, best, overall):
    width, height = 1100, 1185
    card_x, card_w, card_h, gap = 50, 1000, 220, 24
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs>',
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#080b12"/><stop offset="1" stop-color="#111827"/></linearGradient>',
        '<linearGradient id="summary" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#111827"/><stop offset="1" stop-color="#171d2b"/></linearGradient>',
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="#000" flood-opacity="0.28"/></filter>',
        '<style>.title{font-family:Arial,Helvetica,sans-serif;fill:#f8fafc;font-weight:700}.muted{font-family:Arial,Helvetica,sans-serif;fill:#94a3b8}.body{font-family:Arial,Helvetica,sans-serif;fill:#e2e8f0}</style>',
        '</defs>',
        '<rect width="100%" height="100%" rx="22" fill="url(#bg)"/>',
        '<text x="550" y="72" text-anchor="middle" class="muted" font-size="16" letter-spacing="4">DSA PROGRESS</text>',
        f'<text x="550" y="137" text-anchor="middle" class="title" font-size="54">{total} <tspan fill="#94a3b8" font-size="30">Problems Solved</tspan></text>',
        '<rect x="95" y="165" width="910" height="76" rx="14" fill="url(#summary)" stroke="#2b3547"/>',
        f'<text x="200" y="212" text-anchor="middle" font-family="Arial" font-size="19" font-weight="700" fill="#4ade80">Easy {overall["Easy"]}</text>',
        f'<text x="430" y="212" text-anchor="middle" font-family="Arial" font-size="19" font-weight="700" fill="#facc15">Medium {overall["Medium"]}</text>',
        f'<text x="650" y="212" text-anchor="middle" font-family="Arial" font-size="19" font-weight="700" fill="#f87171">Hard {overall["Hard"]}</text>',
        f'<text x="875" y="212" text-anchor="middle" font-family="Arial" font-size="19" font-weight="700" fill="#38bdf8">Unknown {overall["Unknown"]}</text>',
        '<line x1="325" y1="185" x2="325" y2="221" stroke="#334155"/><line x1="540" y1="185" x2="540" y2="221" stroke="#334155"/><line x1="760" y1="185" x2="760" y2="221" stroke="#334155"/>',
        '<rect x="235" y="259" width="300" height="72" rx="14" fill="#111827" stroke="#263043"/><text x="265" y="290" font-size="20">🔥</text><text x="300" y="287" class="muted" font-size="14">CURRENT STREAK</text>',
        f'<text x="300" y="315" class="title" font-size="23">{current} day{"s" if current != 1 else ""}</text>',
        '<rect x="565" y="259" width="300" height="72" rx="14" fill="#111827" stroke="#263043"/><text x="595" y="290" font-size="20">🏆</text><text x="630" y="287" class="muted" font-size="14">BEST STREAK</text>',
        f'<text x="630" y="315" class="title" font-size="23">{best} day{"s" if best != 1 else ""}</text>',
        '<text x="550" y="381" text-anchor="middle" class="muted" font-size="15" letter-spacing="3">PLATFORMS</text>',
        '<line x1="80" y1="381" x2="350" y2="381" stroke="#263043"/><line x1="750" y1="381" x2="1020" y2="381" stroke="#263043"/>',
    ]

    for i, platform in enumerate(("LeetCode", "CodeChef", "HackerRank")):
        rows = platform_rows[platform]
        y = 405 + i * (card_h + gap)
        primary, secondary = PLATFORM_COLORS[platform]
        languages, topics = details(rows)
        d = counts(rows)
        lang = " · ".join(f"{k}: {v}" for k, v in languages.most_common()) or "—"
        topic = " · ".join(f"{k}: {v}" for k, v in topics.most_common(3)) or "—"
        parts += [
            f'<rect x="{card_x}" y="{y}" width="{card_w}" height="{card_h}" rx="18" fill="#0d1117" stroke="{primary}" stroke-opacity="0.75" filter="url(#shadow)"/>',
            f'<rect x="{card_x + 38}" y="{y + 38}" width="64" height="64" rx="16" fill="{primary}"/>',
            logo_markup(platform, card_x + 38, y + 38, 64),
            f'<text x="{card_x + 125}" y="{y + 68}" class="title" font-size="29">{esc(platform)}</text>',
            f'<rect x="{card_x + 805}" y="{y + 40}" width="145" height="52" rx="13" fill="{secondary}" fill-opacity="0.28" stroke="{primary}" stroke-opacity="0.7"/><text x="{card_x + 877}" y="{y + 62}" text-anchor="middle" class="muted" font-size="12">SOLVED</text><text x="{card_x + 877}" y="{y + 84}" text-anchor="middle" class="title" font-size="20">{len(rows)}</text>',
            f'<line x1="{card_x + 125}" y1="{y + 112}" x2="{card_x + 950}" y2="{y + 112}" stroke="#263043"/>',
            f'<text x="{card_x + 125}" y="{y + 142}" font-family="Arial" font-size="16" font-weight="700" fill="#4ade80">Easy {d["Easy"]}</text><text x="{card_x + 285}" y="{y + 142}" font-family="Arial" font-size="16" font-weight="700" fill="#facc15">Medium {d["Medium"]}</text><text x="{card_x + 465}" y="{y + 142}" font-family="Arial" font-size="16" font-weight="700" fill="#f87171">Hard {d["Hard"]}</text><text x="{card_x + 620}" y="{y + 142}" font-family="Arial" font-size="16" font-weight="700" fill="#38bdf8">Unknown {d["Unknown"]}</text>',
            f'<rect x="{card_x + 125}" y="{y + 153}" width="380" height="52" rx="10" fill="#111827" stroke="#263043"/><text x="{card_x + 143}" y="{y + 176}" class="muted" font-size="13">Languages</text><text x="{card_x + 143}" y="{y + 197}" class="body" font-size="17" font-weight="700">{esc(lang)}</text>',
            f'<rect x="{card_x + 525}" y="{y + 153}" width="425" height="52" rx="10" fill="#111827" stroke="#263043"/><text x="{card_x + 543}" y="{y + 176}" class="muted" font-size="13">Topics</text><text x="{card_x + 543}" y="{y + 197}" class="body" font-size="17" font-weight="700">{esc(topic)}</text>',
        ]

    parts.append('<text x="550" y="1148" text-anchor="middle" class="muted" font-size="13">Automatically generated from accepted submissions</text>')
    parts.append('</svg>')
    DASHBOARD_SVG.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_SVG.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    rows = unique_records(load_records())
    overall = counts(rows)
    current, best = streaks(rows)
    platform_rows = {p: [r for r in rows if r.get("platform") == p] for p in ("LeetCode", "CodeChef", "HackerRank")}
    write_dashboard_svg(platform_rows, len(rows), current, best, overall)
    lines = [
        "# DSA Solutions", "", "Automated accepted-submission archive for LeetCode, CodeChef and HackerRank.", "", "## 📊 Progress Dashboard", "",
        f'<h2 align="center">Total Progress — {len(rows)} Problems Solved</h2>', "",
        f'<p align="center"><b>Easy {overall["Easy"]} · Medium {overall["Medium"]} · Hard {overall["Hard"]}' + (f' · Unknown {overall["Unknown"]}' if overall["Unknown"] else "") + "</b></p>", "",
        f'<p align="center">🔥 Current streak: <b>{current} day{"s" if current != 1 else ""}</b> &nbsp;&nbsp; 🏆 Best streak: <b>{best} day{"s" if best != 1 else ""}</b></p>', "",
        "<h2 align=\"center\">Platforms</h2>", "", '<p align="center"><img src="assets/dashboard.svg" alt="DSA platform progress dashboard" width="100%"></p>', "", "---", "",
        "## 📁 Repository Layout", "`Platform / Language / Topic / Difficulty / Problem.cpp`", "", "_This dashboard is automatically regenerated after every sync._", ""
    ]
    README.write_text("\n".join(lines), encoding="utf-8")
    print(f"Dashboard updated: {len(rows)} unique solved problems")


if __name__ == "__main__":
    main()
