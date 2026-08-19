from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from http.cookies import SimpleCookie
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

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
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    cookie = os.environ.get("CODECHEF_COOKIE", "").strip()
    if cookie:
        s.headers["Cookie"] = cookie
    return s


def browser_cookies(cookie_header: str) -> list[dict]:
    if not cookie_header:
        return []
    parsed = SimpleCookie()
    try:
        parsed.load(cookie_header)
    except Exception:
        return []
    return [
        {"name": morsel.key, "value": morsel.value, "domain": ".codechef.com", "path": "/"}
        for morsel in parsed.values()
    ]


def make_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36")
    return webdriver.Chrome(options=options)


def add_cookie_auth(driver):
    cookie_header = os.environ.get("CODECHEF_COOKIE", "").strip()
    if not cookie_header:
        return
    for cookie in browser_cookies(cookie_header):
        try:
            driver.add_cookie(cookie)
        except Exception:
            pass


def recent_submissions(s: requests.Session, username: str, pages: int = 3) -> list[dict]:
    """Use a real browser because CodeChef renders Recent Activity dynamically."""
    driver = make_driver()
    found: dict[str, dict] = {}
    try:
        driver.get(f"{BASE}/users/{username}")
        add_cookie_auth(driver)
        driver.refresh()

        WebDriverWait(driver, 30).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "div.widget.recent-activity table.dataTable tr")
            or d.find_elements(By.CSS_SELECTOR, "table.dataTable tr")
        )

        selectors = [
            "div.widget.recent-activity table.dataTable tr",
            "div.recent-activity table.dataTable tr",
            "table.dataTable tr",
        ]
        rows = []
        for selector in selectors:
            rows = driver.find_elements(By.CSS_SELECTOR, selector)
            if rows:
                break

        for row in rows:
            text = row.text.strip()
            if not text or ("Problem" in text and "Result" in text):
                continue
            if not re.search(r"\(\s*100\s*\)|\bAccepted\b|\bAC\b", text, re.I):
                continue

            links = row.find_elements(By.TAG_NAME, "a")
            solution_id = None
            problem = "Unknown"
            language = "Unknown"
            for link in links:
                href = link.get_attribute("href") or ""
                m = re.search(r"/viewsolution/(\d+)", href)
                if m:
                    solution_id = m.group(1)
                if "/problems/" in href:
                    m = re.search(r"/problems/([A-Za-z0-9_]+)", href)
                    if m:
                        problem = m.group(1)
                elif "/problem/" in href:
                    m = re.search(r"/problem[s]?/([A-Za-z0-9_]+)", href)
                    if m:
                        problem = m.group(1)

            cells = row.find_elements(By.TAG_NAME, "td")
            cell_text = [c.text.strip() for c in cells]
            if cell_text:
                if len(cell_text) >= 4:
                    language = cell_text[3] or language
                if problem == "Unknown" and len(cell_text) >= 2:
                    problem = re.sub(r"\s+", " ", cell_text[1]).strip().split("\n")[0] or "Unknown"

            if solution_id:
                found[solution_id] = {
                    "id": solution_id,
                    "problem": problem,
                    "language": language,
                    "row": text,
                }

        return list(found.values())
    finally:
        driver.quit()


def extract_solution(s: requests.Session, submission_id: str) -> tuple[str, str, str]:
    """Extract source from the rendered CodeChef View Solution page.

    CodeChef currently renders the source client-side, so a plain requests GET
    can return the page without the actual source. Selenium is used here too,
    with the same authenticated cookie as the profile scraper.
    """
    driver = make_driver()
    try:
        driver.get(f"{BASE}/viewsolution/{submission_id}")
        add_cookie_auth(driver)
        driver.refresh()

        WebDriverWait(driver, 30).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "pre, code, textarea, .CodeMirror-code, .cm-content, .ace_text-layer")
        )

        # Prefer elements that are normally dedicated to source code.
        selectors = [
            "pre",
            ".CodeMirror-code",
            ".cm-content",
            ".ace_text-layer",
            "textarea",
            "code",
            "[class*='source-code']",
            "[class*='source_code']",
            "[class*='code-container']",
            "[class*='code-container'] *",
        ]

        candidates = []
        for selector in selectors:
            for element in driver.find_elements(By.CSS_SELECTOR, selector):
                try:
                    text = element.text or element.get_attribute("value") or element.get_attribute("textContent") or ""
                except Exception:
                    continue
                text = text.strip()
                if len(text) < 20:
                    continue
                candidates.append(text)

        # Also inspect elements whose class/id explicitly mentions source/code.
        for element in driver.find_elements(By.CSS_SELECTOR, "[class*='code'], [id*='code'], [class*='source'], [id*='source']"):
            try:
                text = element.text or element.get_attribute("value") or element.get_attribute("textContent") or ""
            except Exception:
                continue
            text = text.strip()
            if len(text) >= 20:
                candidates.append(text)

        # Score candidates so the actual source wins over page/UI text.
        unique = list(dict.fromkeys(candidates))
        code_markers = [
            "#include", "using namespace", "int main", "class Solution", "public:",
            "private:", "return ", "def ", "import ", "#include", "System.out",
            "console.log", "fn main", "package main", "{", ";",
        ]

        def score(text: str) -> int:
            lines = text.count("\n") + 1
            marker_hits = sum(text.count(marker) for marker in code_markers)
            return min(len(text), 20000) + marker_hits * 1000 + min(lines, 200) * 10

        code = max(unique, key=score) if unique else ""
        code = code.strip()

        # Determine language from visible page text.
        page_text = driver.find_element(By.TAG_NAME, "body").text
        language = "Unknown"
        for candidate in ("C++", "C", "Python", "Java", "JavaScript", "Go", "Rust"):
            if re.search(rf"\b{re.escape(candidate)}\b", page_text, re.I):
                language = candidate
                break

        return code, language, page_text
    finally:
        driver.quit()


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
                rating = m.group(1)
                break
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
            language, ext = language_ext(row.get("language") or language_raw)
            title, (rating, tag) = problem_metadata(s, row["problem"])
            difficulty = difficulty_bucket(rating)
            key = f"codechef::{row['id']}"
            if key in records:
                print(f"[{i}/{len(rows)}] {row['id']}: already synced")
                continue
            path = ROOT / "CodeChef" / safe(language) / safe(tag) / safe(difficulty) / f"{safe(row['problem'])}-{safe(title)}.{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code + "\n", encoding="utf-8")
            records[key] = {
                "platform": "CodeChef",
                "submission_id": row["id"],
                "problem_id": row["problem"],
                "title": title,
                "language": language,
                "difficulty": difficulty,
                "tags": [tag],
                "solution_path": str(path.relative_to(ROOT)),
                "source_hash": hashlib.sha256(code.encode()).hexdigest(),
            }
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
