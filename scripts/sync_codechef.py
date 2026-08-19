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
BASE = "https://www.codechef.com"


def load_records():
    return json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}


def save_records(records):
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def safe(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip()
    return re.sub(r"\s+", "-", value)[:100] or "Unknown"


def language_ext(language: str) -> tuple[str, str]:
    v = (language or "").lower()
    if "c++" in v or "cpp" in v: return "C++", "cpp"
    if v in {"c", "c11", "c17"}: return "C", "c"
    if "python" in v: return "Python", "py"
    if "java" in v: return "Java", "java"
    if "javascript" in v: return "JavaScript", "js"
    if "go" in v or "golang" in v: return "Go", "go"
    if "rust" in v: return "Rust", "rs"
    return language or "Unknown", "txt"


def difficulty_bucket(rating_text: str) -> str:
    try:
        rating = int(re.sub(r"[^0-9]", "", rating_text))
    except ValueError:
        return "Unknown"
    if rating < 1000: return "Easy"
    if rating < 1600: return "Medium"
    return "Hard"


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 DSASolutions/1.0", "Accept-Language": "en-US,en;q=0.9"})
    cookie = os.environ.get("CODECHEF_COOKIE", "").strip()
    if cookie:
        s.headers["Cookie"] = cookie
    return s


def recent_submissions(s: requests.Session, username: str, pages: int = 3) -> list[dict]:
    found = {}
    for page in range(pages):
        url = f"{BASE}/recent/user?user_handle={username}&page={page}"
        r = s.get(url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for link in soup.find_all("a", href=True):
            m = re.search(r"/viewsolution/(\d+)", link["href"])
            if not m:
                continue
            row = link.find_parent("tr")
            text = row.get_text(" ", strip=True) if row else link.get_text(" ", strip=True)
            if re.search(r"\bAC\b|Accepted", text, re.I):
                sid = m.group(1)
                problem = "Unknown"
                problem_match = re.search(r"\b([A-Z][A-Z0-9_]{1,20})\b", text)
                if problem_match:
                    problem = problem_match.group(1)
                found[sid] = {"id": sid, "problem": problem, "row": text}
    return list(found.values())


def extract_solution(s: requests.Session, submission_id: str) -> tuple[str, str, str]:
    r = s.get(f"{BASE}/viewsolution/{submission_id}", timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    language = "Unknown"
    for candidate in ("C++", "C", "Python", "Java", "JavaScript", "Go", "Rust"):
        if candidate.lower() in text.lower():
            language = candidate
            break
    code = ""
    for selector in ("pre", "code", "textarea"):
        node = soup.select_one(selector)
        if node and len(node.get_text()) > len(code):
            code = node.get_text()
    if not code:
        # CodeChef may render source in a JS data attribute.
        for node in soup.find_all(attrs={"data-code": True}):
            if len(node.get("data-code", "")) > len(code):
                code = node.get("data-code", "")
    return code.strip(), language, text


def problem_metadata(s: requests.Session, problem: str) -> tuple[str, str]:
    r = s.get(f"{BASE}/problems/{problem}", timeout=30)
    if r.status_code >= 400:
        return "Unknown", "Other"
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else problem
    title = re.sub(r"\s*[-|].*CodeChef.*$", "", title, flags=re.I).strip() or problem
    rating = ""
    for node in soup.find_all(string=re.compile(r"difficulty|rating", re.I)):
        parent = node.parent
        if parent:
            txt = parent.parent.get_text(" ", strip=True) if parent.parent else parent.get_text(" ", strip=True)
            m = re.search(r"\b([0-9]{2,4})\b", txt)
            if m:
                rating = m.group(1); break
    tags = []
    for a in soup.find_all("a", href=True):
        if "/tags/" in a["href"]:
            t = a.get_text(" ", strip=True)
            if t and t not in tags:
                tags.append(t)
    return title, (rating, tags[0] if tags else "Other")


def main():
    username = os.environ.get("CODECHEF_USERNAME", "").strip()
    if not username:
        print("CodeChef skipped: CODECHEF_USERNAME secret is not configured")
        return
    s = session()
    records = load_records()
    rows = recent_submissions(s, username)
    print(f"CodeChef accepted submissions discovered: {len(rows)}")
    added = 0
    for i, row in enumerate(rows, 1):
        try:
            code, language_raw, page_text = extract_solution(s, row["id"])
            if not code:
                print(f"[{i}/{len(rows)}] {row['id']}: source unavailable")
                continue
            language, ext = language_ext(language_raw)
            title, (rating, tag) = problem_metadata(s, row["problem"])
            difficulty = difficulty_bucket(rating)
            key = f"codechef::{row['id']}"
            if key in records:
                print(f"[{i}/{len(rows)}] {row['id']}: already synced")
                continue
            path = ROOT / "CodeChef" / safe(language) / safe(tag) / safe(difficulty) / f"{safe(row['problem'])}-{safe(title)}.{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code + "\n", encoding="utf-8")
            records[key] = {"platform":"CodeChef","submission_id":row["id"],"problem_id":row["problem"],"title":title,"language":language,"difficulty":difficulty,"tags":[tag],"solution_path":str(path.relative_to(ROOT)),"source_hash":hashlib.sha256(code.encode()).hexdigest()}
            added += 1
            print(f"[{i}/{len(rows)}] {row['problem']}: synced -> {path.relative_to(ROOT)}")
        except Exception as exc:
            print(f"[{i}/{len(rows)}] {row['id']}: ERROR: {exc}")
    save_records(records)
    print(f"CodeChef solutions added: {added}")
    if added:
        subprocess.run(["git", "add", "."], cwd=ROOT, check=True)
        subprocess.run(["git", "commit", "-m", f"sync: add {added} CodeChef solution(s)"], cwd=ROOT, check=True)
        subprocess.run(["git", "push"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
