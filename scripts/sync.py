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


def session() -> requests.Session:
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
        "User-Agent": "Mozilla/5.0 DSASolutions/6.0",
        "X-CSRFToken": csrf,
    })
    return s


def gql(s: requests.Session, query: str, variables: dict, operation: str) -> dict:
    payload = {"operationName": operation, "query": query, "variables": variables}
    last = None
    for attempt in range(3):
        try:
            r = s.post(GRAPHQL, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            if data.get("errors"):
                messages = "; ".join(str(e.get("message", "GraphQL error")) for e in data["errors"])
                raise RuntimeError(messages)
            return data
        except Exception as exc:
            last = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"LeetCode request failed: {last}")


def verify(s: requests.Session) -> str:
    query = "query globalData { userStatus { isSignedIn username userId } }"
    status = ((gql(s, query, {}, "globalData").get("data") or {}).get("userStatus") or {})
    if not status.get("isSignedIn"):
        raise RuntimeError("LeetCode authentication rejected")
    return status.get("username") or "unknown"


def accepted_questions(s: requests.Session) -> list[dict]:
    # This is the established questionList API. The status filter is AC, so
    # LeetCode itself selects the user's accepted questions; we do not depend
    # on the unreliable per-question `status` field from problemsetQuestionListV2.
    query = """
    query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
      problemsetQuestionList: questionList(categorySlug: $categorySlug, limit: $limit, skip: $skip, filters: $filters) {
        total: totalNum
        questions: data {
          frontendQuestionId: questionFrontendId
          title
          titleSlug
          difficulty
          status
          topicTags { name slug }
        }
      }
    }
    """

    out: list[dict] = []
    skip = 0
    limit = 100
    while True:
        result = gql(
            s,
            query,
            {"categorySlug": "", "skip": skip, "limit": limit, "filters": {"status": "AC"}},
            "problemsetQuestionList",
        )
        listing = ((result.get("data") or {}).get("problemsetQuestionList") or {})
        batch = listing.get("questions") or []
        total = int(listing.get("total") or 0)
        out.extend(batch)
        print(f"LeetCode AC page {skip // limit + 1}: {len(batch)} problems (total: {total})")
        skip += len(batch)
        if not batch or skip >= total or len(batch) < limit:
            break
    print(f"LeetCode accepted problems found: {len(out)}")
    return out


def accepted_submission(s: requests.Session, slug: str) -> dict | None:
    # questionSubmissionList supports an explicit status=10 (Accepted),
    # avoiding the generic submissionList endpoint that has changed behavior.
    query = """
    query questionSubmissionList($offset: Int!, $limit: Int!, $lastKey: String, $questionSlug: String!, $lang: Int, $status: Int) {
      questionSubmissionList(offset: $offset, limit: $limit, lastKey: $lastKey, questionSlug: $questionSlug, lang: $lang, status: $status) {
        submissions { id titleSlug status statusDisplay lang timestamp }
      }
    }
    """
    result = gql(
        s,
        query,
        {"offset": 0, "limit": 1, "lastKey": None, "questionSlug": slug, "lang": None, "status": 10},
        "questionSubmissionList",
    )
    listing = ((result.get("data") or {}).get("questionSubmissionList") or {})
    submissions = listing.get("submissions") or []
    return submissions[0] if submissions else None


def submission_source(s: requests.Session, submission_id: int) -> dict | None:
    query = """
    query submissionDetails($submissionId: Int!) {
      submissionDetails(submissionId: $submissionId) {
        code
        timestamp
        lang { name langSlug }
      }
    }
    """
    result = gql(s, query, {"submissionId": submission_id}, "submissionDetails")
    return ((result.get("data") or {}).get("submissionDetails") or None)


def language(value: str) -> str:
    return {
        "cpp": "C++", "c++": "C++", "python": "Python", "python3": "Python",
        "java": "Java", "javascript": "JavaScript", "typescript": "TypeScript",
        "c": "C", "csharp": "C#", "golang": "Go", "rust": "Rust",
    }.get(value.lower(), value)


def safe(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip()
    return re.sub(r"\s+", "-", value)[:100] or "Unknown"


def topic(tags: tuple[str, ...]) -> str:
    priority = [
        "Array", "String", "Hash Table", "Two Pointers", "Binary Search", "Linked List",
        "Stack", "Queue", "Tree", "Graph", "Dynamic Programming", "Greedy",
        "Backtracking", "Heap", "Sorting", "Math", "Bit Manipulation",
    ]
    low = {x.lower() for x in tags}
    return next((x for x in priority if x.lower() in low), tags[0] if tags else "Other")


def ext(lang: str) -> str:
    return {"C++": "cpp", "C": "c", "Python": "py", "Java": "java", "JavaScript": "js", "TypeScript": "ts", "Go": "go", "Rust": "rs"}.get(lang, "txt")


def write_solution(sub: Submission) -> Path:
    path = ROOT / "LeetCode" / safe(sub.language) / safe(topic(sub.tags)) / safe(sub.difficulty or "Unknown") / f"{safe(sub.problem_id)}-{safe(sub.title)}.{ext(sub.language)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sub.source.rstrip() + "\n", encoding="utf-8")
    return path


def dashboard(records: dict) -> None:
    counts = {d: sum(1 for r in records.values() if r.get("difficulty") == d) for d in ("Easy", "Medium", "Hard")}
    text = [
        "# DSA Solutions", "",
        "Automated accepted-submission archive.", "",
        "## Progress",
        f"**{len(records)} solved** — Easy: {counts['Easy']} · Medium: {counts['Medium']} · Hard: {counts['Hard']}", "",
        "## Layout", "`LeetCode / Language / Topic / Difficulty / Problem.cpp`", "",
        "Accepted LeetCode submissions are synchronized by GitHub Actions.",
    ]
    (ROOT / "README.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def main() -> None:
    records = load_records()
    s = session()
    username = verify(s)
    print(f"LeetCode authenticated user: {username}")

    questions = accepted_questions(s)
    found = 0
    added = 0

    for i, q in enumerate(questions, 1):
        slug = q.get("titleSlug")
        if not slug:
            continue
        try:
            sub = accepted_submission(s, slug)
            if not sub:
                print(f"[{i}/{len(questions)}] {slug}: no accepted submission")
                continue

            detail = submission_source(s, int(sub["id"]))
            if not detail or not detail.get("code"):
                print(f"[{i}/{len(questions)}] {slug}: source unavailable")
                continue

            tags = tuple(t["name"] for t in q.get("topicTags") or [] if t.get("name"))
            lang = language((detail.get("lang") or {}).get("name") or sub.get("lang") or "Unknown")
            difficulty = q.get("difficulty") if q.get("difficulty") in {"Easy", "Medium", "Hard"} else None
            solution = Submission(
                "LeetCode",
                str(q.get("frontendQuestionId") or slug),
                q.get("title") or slug,
                slug,
                lang,
                detail["code"],
                str(detail.get("timestamp") or sub.get("timestamp") or ""),
                difficulty,
                tags,
                str(sub["id"]),
            )
            found += 1

            if solution.key in records:
                print(f"[{i}/{len(questions)}] {slug}: already synced")
                continue

            path = write_solution(solution)
            records[solution.key] = {
                **asdict(solution),
                "tags": list(solution.tags),
                "source_hash": solution.source_hash,
                "solution_path": str(path.relative_to(ROOT)),
            }
            added += 1
            print(f"[{i}/{len(questions)}] {slug}: synced -> {path.relative_to(ROOT)}")
        except Exception as exc:
            print(f"[{i}/{len(questions)}] {slug}: ERROR: {exc}")

    save_records(records)
    dashboard(records)
    print(f"LeetCode accepted solutions found: {found}; added: {added}")

    if added:
        git("add", ".")
        git("commit", "-m", f"sync: add {added} accepted LeetCode solution(s)")
        git("push")


if __name__ == "__main__":
    main()
