from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "submissions.json"
README = ROOT / "README.md"

PLATFORM_EMOJI = {
    "LeetCode": "🟧",
    "CodeChef": "🟪",
    "HackerRank": "🟩",
}


def load_records() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}


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


def streaks(records: dict) -> tuple[int, int]:
    dates = sorted({d for r in records.values() if (d := parse_date(r)) is not None})
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


def platform_block(platform: str, rows: list[dict]) -> list[str]:
    counts = Counter(r.get("difficulty") for r in rows)
    languages = Counter(r.get("language") or "Unknown" for r in rows)
    topics = Counter((r.get("tags") or ["Other"])[0] for r in rows)
    lang_text = " · ".join(f"{k}: {v}" for k, v in languages.most_common()) or "—"
    topic_text = " · ".join(f"{k}: {v}" for k, v in topics.most_common(5)) or "—"

    return [
        "<table align=\"center\" width=\"92%\">",
        "<tr><td align=\"center\">",
        f"<h2>{PLATFORM_EMOJI.get(platform, '⬜')} {platform}</h2>",
        f"<h3>{len(rows)} solved</h3>",
        f"<b>Easy {counts['Easy']} · Medium {counts['Medium']} · Hard {counts['Hard']}</b><br>",
        f"Languages: {lang_text}<br>",
        f"Topics: {topic_text}",
        "</td></tr>",
        "</table>",
    ]


def main() -> None:
    records = load_records()
    rows = list(records.values())
    difficulties = Counter(r.get("difficulty") for r in rows)
    current, best = streaks(records)

    lines = [
        "# DSA Solutions",
        "",
        "Automated accepted-submission archive for LeetCode, CodeChef and HackerRank.",
        "",
        "## 📊 Progress Dashboard",
        "",
        f"<h2 align=\"center\">Total Progress — {len(rows)} problems solved</h2>",
        "",
        f"<p align=\"center\"><b>Easy {difficulties['Easy']} · Medium {difficulties['Medium']} · Hard {difficulties['Hard']}</b></p>",
        "",
        f"<p align=\"center\">🔥 Current streak: <b>{current} day{'s' if current != 1 else ''}</b> &nbsp;&nbsp; 🏆 Best streak: <b>{best} day{'s' if best != 1 else ''}</b></p>",
        "",
        "<h2 align=\"center\">Platforms</h2>",
        "",
    ]

    for platform in ("LeetCode", "CodeChef", "HackerRank"):
        platform_rows = [r for r in rows if r.get("platform") == platform]
        lines.extend(platform_block(platform, platform_rows))
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 📁 Repository Layout",
        "`Platform / Language / Topic / Difficulty / Problem.cpp`",
        "",
        "_This dashboard is automatically regenerated after every sync._",
        "",
    ])

    README.write_text("\n".join(lines), encoding="utf-8")
    print(f"Dashboard updated: {len(rows)} total solutions")


if __name__ == "__main__":
    main()
