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

PLATFORM_EMOJI = {
    "LeetCode": "■",
    "CodeChef": "■",
    "HackerRank": "■",
}

PLATFORM_ICON_COLORS = {
    "LeetCode": "#ff6b35",
    "CodeChef": "#8b5cf6",
    "HackerRank": "#34d399",
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


def difficulty_text(rows: list[dict]) -> str:
    counts = Counter(r.get("difficulty") for r in rows)
    parts = [f"Easy {counts['Easy']}", f"Medium {counts['Medium']}", f"Hard {counts['Hard']}"]
    if counts["Unknown"]:
        parts.append(f"Unknown {counts['Unknown']}")
    return " · ".join(parts)


def platform_details(platform: str, rows: list[dict]) -> tuple[str, str, str]:
    languages = Counter(r.get("language") or "Unknown" for r in rows)
    topics = Counter((r.get("tags") or ["Other"])[0] for r in rows)
    lang_text = " · ".join(f"{k}: {v}" for k, v in languages.most_common()) or "—"
    topic_text = " · ".join(f"{k}: {v}" for k, v in topics.most_common(5)) or "—"
    return difficulty_text(rows), lang_text, topic_text


def svg_text(value: str) -> str:
    return html.escape(value, quote=True)


def write_dashboard_svg(platform_rows: dict[str, list[dict]]) -> None:
    """Generate equal-width platform cards as SVG so GitHub's table CSS cannot resize them."""
    width = 1000
    card_width = 920
    card_height = 210
    gap = 28
    height = len(platform_rows) * card_height + (len(platform_rows) - 1) * gap + 20

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0d1117"/>',
    ]

    for index, platform in enumerate(("LeetCode", "CodeChef", "HackerRank")):
        rows = platform_rows[platform]
        y = 10 + index * (card_height + gap)
        difficulty, languages, topics = platform_details(platform, rows)
        icon_color = PLATFORM_ICON_COLORS[platform]

        parts.extend([
            f'<rect x="40" y="{y}" width="{card_width}" height="{card_height}" rx="10" fill="#0d1117" stroke="#30363d"/>',
            f'<rect x="360" y="{y + 28}" width="34" height="34" rx="6" fill="{icon_color}"/>',
            f'<text x="410" y="{y + 56}" fill="#f0f6fc" font-family="Arial, Helvetica, sans-serif" font-size="32" font-weight="700">{svg_text(platform)}</text>',
            f'<line x1="65" y1="{y + 82}" x2="935" y2="{y + 82}" stroke="#30363d"/>',
            f'<text x="500" y="{y + 126}" text-anchor="middle" fill="#f0f6fc" font-family="Arial, Helvetica, sans-serif" font-size="26" font-weight="700">{len(rows)} solved</text>',
            f'<text x="500" y="{y + 162}" text-anchor="middle" fill="#f0f6fc" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700">{svg_text(difficulty)}</text>',
            f'<text x="500" y="{y + 188}" text-anchor="middle" fill="#f0f6fc" font-family="Arial, Helvetica, sans-serif" font-size="16">Languages: {svg_text(languages)}</text>',
            f'<text x="500" y="{y + 208}" text-anchor="middle" fill="#f0f6fc" font-family="Arial, Helvetica, sans-serif" font-size="15">Topics: {svg_text(topics)}</text>',
        ])

    parts.append('</svg>')
    DASHBOARD_SVG.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_SVG.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    raw_records = load_records()
    rows = unique_records(raw_records)
    difficulties = Counter(r.get("difficulty") for r in rows)
    current, best = streaks(rows)
    platform_rows = {
        platform: [r for r in rows if r.get("platform") == platform]
        for platform in ("LeetCode", "CodeChef", "HackerRank")
    }

    write_dashboard_svg(platform_rows)

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
