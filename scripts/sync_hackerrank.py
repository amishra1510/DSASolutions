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
    v = (value or "").lower()
    if "c++" in v or "cpp" in v: return "C++", "cpp"
    if v == "c": return "C", "c"
    if "python" in v: return "Python", "py"
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
    s.headers.update({"User-Agent": "Mozilla/5.0 DSASolutions/1.0", "Accept-Language": "en-US,en;q=0.9"})
    cookie = os.environ.get("HACKERRANK_COOKIE", "").strip()
    if cookie:
        s.headers["Cookie"] = cookie
    return s


def discover_submissions(s: requests.Session, username: str) -> list[dict]:
    r = s.get(f"{BASE}/submissions/all", timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    rows = []
    seen = set()
    for node in soup.find_all("a", href=True):
        href = node["href"]
        m = re.search(r"/challenges/([^/?#]+)/", href)
        if not m:
            continue
        slug = m.group(1)
        row = node.find_parent("tr") or node.parent
        text = row.get_text(" ", strip=True) if row else node.get_text(" ", strip=True)
        if not re.search(r"Accepted|Success|100%|Score", text, re.I):
            continue
        key = slug
        if key in seen:
            continue
        seen.add(key)
        language = "Unknown"
        for candidate in ("C++", "C", "Python", "Java", "JavaScript", "TypeScript", "Ruby", "Kotlin", "Go", "Swift"):
            if re.search(rf"\b{re.escape(candidate)}\b", text, re.I):
                language = candidate
                break
        rows.append({"slug": slug, "title": node.get_text(" ", strip=True) or slug, "language": language})
    return rows


def download_solution(s: requests.Session, username: str, slug: str) -> str:
    url = f"{BASE}/rest/contests/master/challenges/{slug}/hackers/{username}/download_solution"
    r = s.get(url, timeout=30)
    if r.status_code == 200 and r.text.strip():
        return r.text.strip()
    raise RuntimeError(f"download_solution returned HTTP {r.status_code}")


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


def main():
    username = os.environ.get("HACKERRANK_USERNAME", "").strip()
    cookie = os.environ.get("HACKERRANK_COOKIE", "").strip()
    if not username or not cookie:
        print("HackerRank skipped: configure HACKERRANK_USERNAME and HACKERRANK_COOKIE secrets")
        return
    s = session()
    records = load_records()
    rows = discover_submissions(s, username)
    print(f"HackerRank accepted submissions discovered: {len(rows)}")
    added = 0
    for i, row in enumerate(rows, 1):
        try:
            code = download_solution(s, username, row["slug"])
            language, ext = language_ext(row["language"])
            title, tag = challenge_metadata(s, row["slug"])
            key = f"hackerrank::{row['slug']}::{language.lower()}"
            if key in records:
                print(f"[{i}/{len(rows)}] {row['slug']}: already synced")
                continue
            path = ROOT / "HackerRank" / safe(language) / safe(tag) / "Unknown" / f"{safe(row['slug'])}-{safe(title)}.{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code + "\n", encoding="utf-8")
            records[key] = {"platform":"HackerRank","problem_id":row["slug"],"title":title,"language":language,"difficulty":"Unknown","tags":[tag],"solution_path":str(path.relative_to(ROOT)),"source_hash":hashlib.sha256(code.encode()).hexdigest()}
            added += 1
            print(f"[{i}/{len(rows)}] {row['slug']}: synced -> {path.relative_to(ROOT)}")
        except Exception as exc:
            print(f"[{i}/{len(rows)}] {row['slug']}: ERROR: {exc}")
    save_records(records)
    print(f"HackerRank solutions added: {added}")
    if added:
        subprocess.run(["git", "add", "."], cwd=ROOT, check=True)
        subprocess.run(["git", "commit", "-m", f"sync: add {added} HackerRank solution(s)"], cwd=ROOT, check=True)
        subprocess.run(["git", "push"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
