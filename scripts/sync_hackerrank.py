from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "submissions.json"
BASE = "https://www.hackerrank.com"


def load_records():
    return json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}


def save_records(records):
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def safe(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip()
    return re.sub(r"\s+", "-", value)[:100] or "Unknown"


def language_ext(value: str) -> tuple[str, str]:
    v = (value or "").lower().strip()
    if v in {"pypy3", "pypy 3", "pypy"} or "python" in v:
        return "Python", "py"
    if "c++" in v or "cpp" in v: return "C++", "cpp"
    if v == "c": return "C", "c"
    if "java" in v: return "Java", "java"
    if "javascript" in v: return "JavaScript", "js"
    if "typescript" in v: return "TypeScript", "ts"
    if "ruby" in v: return "Ruby", "rb"
    if "kotlin" in v: return "Kotlin", "kt"
    if "go" in v: return "Go", "go"
    if "swift" in v: return "Swift", "swift"
    return value or "Unknown", "txt"


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{BASE}/submissions/all",
        "X-Requested-With": "XMLHttpRequest",
    })

    cookie = os.environ.get("HACKERRANK_COOKIE", "").strip()
    if cookie:
        s.headers["Cookie"] = cookie
        pairs = {}
        for part in cookie.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                pairs[k.strip()] = v.strip()
        for name in ("csrf_token", "csrfToken", "XSRF-TOKEN", "_csrf"):
            if pairs.get(name):
                s.headers["X-CSRF-Token"] = pairs[name]
                break

    return s


def _extract_models(value) -> list[dict]:
    found: list[dict] = []
    if isinstance(value, dict):
        if "models" in value and isinstance(value["models"], list):
            found.extend(x for x in value["models"] if isinstance(x, dict))
        for child in value.values():
            found.extend(_extract_models(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_extract_models(child))
    return found


def _models_from_html(html: str) -> list[dict]:
    models: list[dict] = []
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        if not text or "submission" not in text.lower():
            continue
        text = text.strip()
        candidates = [text]
        if text.startswith("window.") and "=" in text:
            candidates.append(text.split("=", 1)[1].strip().rstrip(";"))
        for candidate in candidates:
            try:
                models.extend(_extract_models(json.loads(candidate)))
            except Exception:
                pass
    return models


def discover_submissions(s: requests.Session, username: str) -> list[dict]:
    """Return accepted submissions, keeping every submission ID.

    The old implementation collapsed submissions by challenge, which meant a
    second accepted submission for the same problem could disappear before the
    sync code saw it. We deliberately keep every unique submission ID here.
    """
    models: list[dict] = []
    endpoints = [
        f"{BASE}/rest/contests/master/submissions/?offset=0&limit=1000",
        f"{BASE}/rest/contests/master/submissions?offset=0&limit=1000",
        f"{BASE}/rest/contests/master/submissions/?offset=0&limit=100",
    ]

    for api in endpoints:
        r = s.get(api, timeout=30)
        if r.status_code != 200:
            continue
        try:
            data = r.json()
        except ValueError:
            continue
        models.extend(_extract_models(data))
        if models:
            break

    if not models:
        page = s.get(f"{BASE}/submissions/all", timeout=30)
        if page.status_code == 200:
            models = _models_from_html(page.text)

    unique: list[dict] = []
    seen_ids: set[str] = set()
    for model in models:
        sid = model.get("id")
        if sid is None:
            continue
        key = str(sid)
        if key not in seen_ids:
            seen_ids.add(key)
            unique.append(model)

    # Newest first. Do not collapse by challenge: two accepted submissions for
    # the same problem are two distinct events and can each create a commit.
    def submission_sort_key(model):
        try:
            return int(model.get("id", 0))
        except (TypeError, ValueError):
            return 0

    unique.sort(key=submission_sort_key, reverse=True)

    rows: list[dict] = []
    for model in unique:
        if str(model.get("status", "")).lower() != "accepted":
            continue

        challenge = model.get("challenge") or {}
        slug = challenge.get("slug") or model.get("challenge_slug")
        if not slug:
            continue

        language = model.get("language") or model.get("language_name") or "Unknown"
        title = challenge.get("name") or model.get("name") or slug
        rows.append({
            "id": model.get("id"),
            "slug": slug,
            "title": title,
            "language": language,
        })

    return rows


def download_solution(s: requests.Session, username: str, slug: str, submission_id=None) -> str:
    if submission_id is not None:
        url = f"{BASE}/rest/contests/master/challenges/{slug}/submissions/{submission_id}"
        r = s.get(url, timeout=30)
        if r.status_code == 200:
            try:
                model = r.json().get("model", {})
                code = model.get("code")
                if isinstance(code, str) and code.strip():
                    return code.strip()
            except (ValueError, AttributeError):
                pass

    url = f"{BASE}/rest/contests/master/challenges/{slug}/hackers/{username}/download_solution"
    r = s.get(url, timeout=30)
    if r.status_code == 200 and r.text.strip():
        return r.text.strip()
    raise RuntimeError(f"could not download solution (HTTP {r.status_code})")


def challenge_metadata(s: requests.Session, slug: str) -> tuple[str, str]:
    r = s.get(f"{BASE}/challenges/{slug}/problem", timeout=30)
    if r.status_code >= 400:
        return slug, "Other"
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else slug
    title = re.sub(r"\s*[-|].*HackerRank.*$", "", title, flags=re.I).strip() or slug
    tag = "Other"
    for a in soup.find_all("a", href=True):
        if "/domains/" in a["href"] or "/skills/" in a["href"]:
            candidate = a.get_text(" ", strip=True)
            if candidate:
                tag = candidate
                break
    return title, tag


def known_submission_ids(records: dict) -> set[str]:
    ids = set()
    for value in records.values():
        if isinstance(value, dict) and value.get("platform") == "HackerRank":
            sid = value.get("submission_id")
            if sid is not None:
                ids.add(str(sid))
    return ids


def main():
    username = os.environ.get("HACKERRANK_USERNAME", "").strip()
    cookie = os.environ.get("HACKERRANK_COOKIE", "").strip()
    if not username or not cookie:
        print("HackerRank skipped: configure HACKERRANK_USERNAME and HACKERRANK_COOKIE secrets")
        return

    s = session()
    records = load_records()
    rows = discover_submissions(s, username)
    known_ids = known_submission_ids(records)
    print(f"HackerRank accepted submissions discovered: {len(rows)}")

    # Only process submission IDs we have never recorded. Existing solutions in
    # the repo are left alone; the submission record itself is what guarantees
    # that every new accepted submission produces a Git change.
    new_rows = [row for row in rows if str(row.get("id")) not in known_ids]
    print(f"New HackerRank submissions to record: {len(new_rows)}")

    changes = 0
    for i, row in enumerate(new_rows, 1):
        try:
            code = download_solution(s, username, row["slug"], row.get("id"))
            language, ext = language_ext(row["language"])
            title, tag = challenge_metadata(s, row["slug"])
            sid = str(row["id"])

            # Use a submission-specific key. This is the critical difference:
            # repeated submissions of the same problem remain separate events.
            key = f"hackerrank::submission::{sid}"
            if key in records:
                continue

            path = ROOT / "HackerRank" / safe(language) / safe(tag) / "Unknown" / f"{safe(row['slug'])}-{safe(title)}.py"
            path.parent.mkdir(parents=True, exist_ok=True)

            # Do not overwrite the existing solution file for a repeat
            # submission. The JSON submission record is enough to make a
            # distinct Git commit while keeping the archive clean.
            if not path.exists():
                path.write_text(code + "\n", encoding="utf-8")

            records[key] = {
                "platform": "HackerRank",
                "submission_id": row["id"],
                "problem_id": row["slug"],
                "title": title,
                "language": language,
                "difficulty": "Unknown",
                "tags": [tag],
                "solution_path": str(path.relative_to(ROOT)),
                "source_hash": hashlib.sha256(code.encode()).hexdigest(),
            }
            changes += 1
            print(f"[{i}/{len(new_rows)}] {row['slug']}: recorded submission {sid}")
        except Exception as exc:
            print(f"[{i}/{len(new_rows)}] {row['slug']}: ERROR: {exc}")

    save_records(records)
    print(f"HackerRank submission changes: {changes}")
    if changes:
        subprocess.run(["git", "add", "."], cwd=ROOT, check=True)
        subprocess.run(["git", "commit", "-m", f"sync: record {changes} HackerRank submission(s)"], cwd=ROOT, check=True)
        subprocess.run(["git", "push"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
