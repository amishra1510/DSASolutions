from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "submissions.json"
GRAPHQL = "https://leetcode.com/graphql/"


@dataclass(frozen=True)
class Submission:
    platform: str
    problem_id: str
    title: str
    slug: str
    language: str
    source: str
    accepted_at: str
    difficulty: str | None
    tags: tuple[str, ...]
    submission_id: str

    @property
    def key(self) -> str:
        return f"leetcode::{self.problem_id}::{self.language.lower()}"

    @property
    def source_hash(self) -> str:
        return hashlib.sha256(self.source.replace("\r\n", "\n").strip().encode()).hexdigest()


def load_records() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}


def save_records(records: dict) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def make_session() -> requests.Session:
    cookie = os.environ.get("LEETCODE_SESSION")
    csrf = os.environ.get("LEETCODE_CSRF_TOKEN")
    if not cookie or not csrf:
        raise RuntimeError("Missing LEETCODE_SESSION or LEETCODE_CSRF_TOKEN")

    s = requests.Session()
    s.cookies.set("LEETCODE_SESSION", cookie, domain="leetcode.com")
    s.cookies.set("csrftoken", csrf, domain="leetcode.com")
    s.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://leetcode.com",
        "Referer": "https://leetcode.com/",
        "User-Agent": "Mozilla/5.0 DSASolutions/7.0",
        "X-CSRFToken": csrf,
    })
    return s


def gql(s: requests.Session, query: str, variables: dict, operation: str) -> dict:
    payload = {"operationName": operation, "query": query, "variables": variables}
    last = None
    for attempt in range(3):
        try:
            response = s.post(GRAPHQL, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data.get("errors"):
                raise RuntimeError("; ".join(str(e.get("message", "GraphQL error")) for e in data["errors"]))
            return data
        except Exception as exc:
            last = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"LeetCode request failed: {last}")


def verify_login(s: requests.Session) -> str:
    query = "query globalData { userStatus { isSignedIn username userId } }"
    status = ((gql(s, query, {}, "globalData").get("data") or {}).get("userStatus") or {})
    if not status.get("isSignedIn"):
        raise RuntimeError("LeetCode authentication rejected")
    return status.get("username") or "unknown"


def fetch_recent_accepted(s: requests.Session, username: str) -> list[dict]:
    """Return LeetCode's own accepted-submission feed.

    IMPORTANT: recentAcSubmissionList is already an AC-only feed. Older versions
    of this script incorrectly treated these records like generic submissions and
    filtered on a missing statusDisplay field, turning valid AC records into zero.
    """
    query = """
    query recentAcSubmissions($username: String!, $limit: Int!) {
      recentAcSubmissionList(username: $username, limit: $limit) {
        id
        title
        titleSlug
        timestamp
      }
    }
    """
    result = gql(s, query, {"username": username, "limit": 100}, "recentAcSubmissions")
    rows = ((result.get("data") or {}).get("recentAcSubmissionList") or [])
    print(f"LeetCode recent AC submissions returned: {len(rows)}")
    return rows


def fetch_question(s: requests.Session, slug: str) -> dict:
    query = """
    query questionTitle($titleSlug: String!) {
      question(titleSlug: $titleSlug) {
        questionId
        questionFrontendId
        title
        titleSlug
        difficulty
        topicTags { name slug }
      }
    }
    """
    result = gql(s, query, {"titleSlug": slug}, "questionTitle")
    return ((result.get("data") or {}).get("question") or {})


def fetch_submission_source(s: requests.Session, submission_id: int) -> dict | None:
    query = """
    query submissionDetails($submissionId: Int!) {
      submissionDetails(submissionId: $submissionId) {
        code
        timestamp
        lang { name langSlug }
        statusCode
      }
    }
    """
    result = gql(s, query, {"submissionId": submission_id}, "submissionDetails")
    return ((result.get("data") or {}).get("submissionDetails") or None)


def canonical_language(value: str) -> str:
    return {
        "cpp": "C++", "c++": "C++", "python": "Python", "python3": "Python",
        "java": "Java", "javascript": "JavaScript", "typescript": "TypeScript",
        "c": "C", "csharp": "C#", "golang": "Go", "rust": "Rust",
    }.get(value.lower(), value)


def safe(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip()
    return re.sub(r"\s+", "-", value)[:100] or "Unknown"


def primary_topic(tags: tuple[str, ...]) -> str:
    priority = [
        "Array", "String", "Hash Table", "Two Pointers", "Binary Search", "Linked List",
        "Stack", "Queue", "Tree", "Graph", "Dynamic Programming", "Greedy",
        "Backtracking", "Heap", "Sorting", "Math", "Bit Manipulation",
    ]
    lowered = {x.lower() for x in tags}
    return next((x for x in priority if x.lower() in lowered), tags[0] if tags else "Other")


def extension(language: str) -> str:
    return {
        "C++": "cpp", "C": "c", "Python": "py", "Java": "java",
        "JavaScript": "js", "TypeScript": "ts", "Go": "go", "Rust": "rs",
    }.get(language, "txt")


def write_solution(submission: Submission) -> Path:
    path = (
        ROOT / "LeetCode" / safe(submission.language) /
        safe(primary_topic(submission.tags)) /
        safe(submission.difficulty or "Unknown") /
        f"{safe(submission.problem_id)}-{safe(submission.title)}.{extension(submission.language)}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(submission.source.rstrip() + "\n", encoding="utf-8")
    return path


def update_dashboard(records: dict) -> None:
    counts = {d: sum(1 for r in records.values() if r.get("difficulty") == d) for d in ("Easy", "Medium", "Hard")}
    text = [
        "# DSA Solutions", "",
        "Automated accepted-submission archive for LeetCode, CodeChef and HackerRank.", "",
        "## Progress",
        f"**{len(records)} synced** — Easy: {counts['Easy']} · Medium: {counts['Medium']} · Hard: {counts['Hard']}", "",
        "## Layout", "`LeetCode / Language / Topic / Difficulty / Problem.cpp`", "",
        "Accepted LeetCode submissions are synchronized by GitHub Actions.",
    ]
    (ROOT / "README.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def main() -> None:
    records = load_records()
    s = make_session()
    username = verify_login(s)
    print(f"LeetCode authenticated user: {username}")

    accepted = fetch_recent_accepted(s, username)
    found = 0
    added = 0

    for index, item in enumerate(accepted, 1):
        slug = item.get("titleSlug")
        if not slug:
            continue
        try:
            question = fetch_question(s, slug)
            if not question:
                print(f"[{index}/{len(accepted)}] {slug}: question metadata unavailable")
                continue

            detail = fetch_submission_source(s, int(item["id"]))
            if not detail or not detail.get("code"):
                print(f"[{index}/{len(accepted)}] {slug}: source unavailable")
                continue

            # recentAcSubmissionList is AC-only. We only additionally guard
            # against an unexpected non-10 detail response when the field exists.
            if detail.get("statusCode") is not None and int(detail["statusCode"]) != 10:
                print(f"[{index}/{len(accepted)}] {slug}: submission is not accepted")
                continue

            tags = tuple(t.get("name") for t in question.get("topicTags") or [] if t.get("name"))
            lang = canonical_language((detail.get("lang") or {}).get("name") or "Unknown")
            difficulty = question.get("difficulty") if question.get("difficulty") in {"Easy", "Medium", "Hard"} else None

            solution = Submission(
                platform="LeetCode",
                problem_id=str(question.get("questionFrontendId") or question.get("questionId") or slug),
                title=question.get("title") or item.get("title") or slug,
                slug=slug,
                language=lang,
                source=detail["code"],
                accepted_at=str(detail.get("timestamp") or item.get("timestamp") or ""),
                difficulty=difficulty,
                tags=tags,
                submission_id=str(item["id"]),
            )
            found += 1

            if solution.key in records:
                print(f"[{index}/{len(accepted)}] {slug}: already synced")
                continue

            path = write_solution(solution)
            records[solution.key] = {
                **asdict(solution),
                "tags": list(solution.tags),
                "source_hash": solution.source_hash,
                "solution_path": str(path.relative_to(ROOT)),
            }
            added += 1
            print(f"[{index}/{len(accepted)}] {slug}: synced -> {path.relative_to(ROOT)}")
        except Exception as exc:
            print(f"[{index}/{len(accepted)}] {slug}: ERROR: {exc}")

    save_records(records)
    update_dashboard(records)
    print(f"LeetCode accepted solutions found: {found}; added: {added}")

    if added:
        git("add", ".")
        git("commit", "-m", f"sync: add {added} accepted LeetCode solution(s)")
        git("push")


if __name__ == "__main__":
    main()
