from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "submissions.json"
LEETCODE = "https://leetcode.com/graphql"


@dataclass(frozen=True)
class Submission:
    platform: str
    problem_id: str
    title: str
    language: str
    source: str
    accepted_at: str
    difficulty: str | None = None
    tags: tuple[str, ...] = ()
    submission_id: str | None = None

    @property
    def key(self) -> str:
        return f"{self.platform.lower()}::{self.problem_id}::{self.language.lower()}"

    @property
    def source_hash(self) -> str:
        return hashlib.sha256(self.source.replace("\r\n", "\n").strip().encode()).hexdigest()


def load_records() -> dict:
    if not DATA.exists():
        return {}
    return json.loads(DATA.read_text(encoding="utf-8"))


def save_records(records: dict) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def leetcode_request(query: str, variables: dict | None = None) -> dict:
    session = os.environ.get("LEETCODE_SESSION")
    csrf = os.environ.get("LEETCODE_CSRF_TOKEN")
    if not session or not csrf:
        raise RuntimeError("Missing LEETCODE_SESSION or LEETCODE_CSRF_TOKEN")

    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        LEETCODE,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://leetcode.com",
            "Referer": "https://leetcode.com/",
            "x-csrftoken": csrf,
            "Cookie": f"LEETCODE_SESSION={session}; csrftoken={csrf}",
            "User-Agent": "Mozilla/5.0 DSASolutions/2.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"LeetCode HTTP {exc.code}") from exc

    if result.get("errors"):
        raise RuntimeError(f"LeetCode GraphQL error: {result['errors'][0].get('message', 'unknown error')}")
    return result


def fetch_accepted_problems() -> list[dict]:
    """Get the authenticated user's solved problems.

    This avoids the unreliable global submissionList endpoint. LeetCode exposes
    the authenticated solved-question list through userProfileQuestions; we then
    ask questionSubmissionList for the latest accepted submission of each problem.
    """
    status = leetcode_request("query { userStatus { isSignedIn username } }")
    user = (status.get("data") or {}).get("userStatus") or {}
    if not user.get("isSignedIn") or not user.get("username"):
        raise RuntimeError("LeetCode authentication rejected or username unavailable")

    print(f"LeetCode authenticated user: {user['username']}")

    query = """query userProfileQuestions($status: StatusFilterEnum!, $skip: Int!, $first: Int!, $sortField: SortFieldEnum!, $sortOrder: SortingOrderEnum!, $keyword: String, $difficulty: [DifficultyEnum!]) {
      userProfileQuestions(
        status: $status
        skip: $skip
        first: $first
        sortField: $sortField
        sortOrder: $sortOrder
        keyword: $keyword
        difficulty: $difficulty
      ) {
        totalNum
        questions {
          questionFrontendId
          titleSlug
          title
          difficulty
          topicTags { name slug }
          lastSubmittedAt
        }
      }
    }"""

    questions: list[dict] = []
    skip = 0
    page_size = 100

    while True:
        result = leetcode_request(query, {
            "status": "ACCEPTED",
            "skip": skip,
            "first": page_size,
            "sortField": "LAST_SUBMITTED_AT",
            "sortOrder": "DESCENDING",
            "keyword": None,
            "difficulty": [],
        })
        data = ((result.get("data") or {}).get("userProfileQuestions") or {})
        batch = data.get("questions") or []
        total = int(data.get("totalNum") or len(batch))
        questions.extend(batch)
        print(f"LeetCode solved problems page {skip // page_size + 1}: {len(batch)} (total reported: {total})")
        skip += len(batch)
        if not batch or skip >= total:
            break

    return questions


def fetch_latest_accepted(question_slug: str) -> dict | None:
    """Return the newest accepted submission for one problem."""
    query = """query questionSubmissionList($offset: Int!, $limit: Int!, $lastKey: String, $questionSlug: String!, $lang: Int, $status: Int) {
      questionSubmissionList(
        offset: $offset
        limit: $limit
        lastKey: $lastKey
        questionSlug: $questionSlug
        lang: $lang
        status: $status
      ) {
        lastKey
        hasNext
        submissions {
          id
          titleSlug
          status
          statusDisplay
          lang
          timestamp
        }
      }
    }"""
    result = leetcode_request(query, {
        "offset": 0,
        "limit": 1,
        "lastKey": None,
        "questionSlug": question_slug,
        "lang": None,
        "status": 10,
    })
    data = ((result.get("data") or {}).get("questionSubmissionList") or {})
    submissions = data.get("submissions") or []
    return submissions[0] if submissions else None


def fetch_submission_code(submission_id: int) -> dict | None:
    query = """query submissionDetails($submissionId: Int!) {
      submissionDetails(submissionId: $submissionId) {
        code
        timestamp
        statusCode
        lang { name verboseName }
        question {
          questionId
          title
          difficulty
          topicTags { name slug }
        }
      }
    }"""
    result = leetcode_request(query, {"submissionId": submission_id})
    return ((result.get("data") or {}).get("submissionDetails") or None)


def fetch_leetcode() -> list[Submission]:
    questions = fetch_accepted_problems()
    print(f"LeetCode accepted problems reported by profile: {len(questions)}")

    out: list[Submission] = []
    for index, question in enumerate(questions, 1):
        slug = question.get("titleSlug")
        if not slug:
            continue

        try:
            submission = fetch_latest_accepted(slug)
            if not submission:
                print(f"[{index}/{len(questions)}] {slug}: no accepted submission returned")
                continue

            detail = fetch_submission_code(int(submission["id"]))
            if not detail or not detail.get("code"):
                print(f"[{index}/{len(questions)}] {slug}: accepted submission found but source unavailable")
                continue

            q = detail.get("question") or {}
            tags = tuple(t["name"] for t in q.get("topicTags") or [] if t.get("name"))
            language = canonical_language(
                (detail.get("lang") or {}).get("name") or submission.get("lang") or "Unknown"
            )
            problem_id = str(q.get("questionId") or question.get("questionFrontendId") or slug)
            difficulty = q.get("difficulty") or question.get("difficulty")
            title = q.get("title") or question.get("title") or slug

            out.append(Submission(
                platform="LeetCode",
                problem_id=problem_id,
                title=title,
                language=language,
                source=detail["code"],
                accepted_at=str(detail.get("timestamp") or submission.get("timestamp") or question.get("lastSubmittedAt") or ""),
                difficulty=difficulty if difficulty in {"Easy", "Medium", "Hard"} else None,
                tags=tags or tuple(t.get("name") for t in question.get("topicTags") or [] if t.get("name")),
                submission_id=str(submission["id"]),
            ))
            print(f"[{index}/{len(questions)}] {problem_id} - {title} [{language}] ✓")
        except Exception as exc:
            # One problematic problem must not kill the complete sync.
            print(f"[{index}/{len(questions)}] {slug}: ERROR: {exc}")

    print(f"LeetCode accepted solutions with source code: {len(out)}")
    return out


def canonical_language(value: str) -> str:
    return {
        "cpp": "C++", "c++": "C++", "python3": "Python",
        "javascript": "JavaScript", "typescript": "TypeScript",
    }.get(value.lower(), value)


def primary_tag(tags: tuple[str, ...]) -> str:
    priority = [
        "Array", "String", "Hash Table", "Two Pointers", "Binary Search",
        "Linked List", "Stack", "Queue", "Tree", "Graph",
        "Dynamic Programming", "Greedy", "Backtracking", "Heap", "Sorting",
    ]
    lower = {x.lower() for x in tags}
    return next((x for x in priority if x.lower() in lower), tags[0] if tags else "Other")


def safe(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip()
    return re.sub(r"\s+", "-", value)[:100] or "Unknown"


def extension(language: str) -> str:
    return {
        "C++": "cpp", "C": "c", "Python": "py", "Java": "java",
        "JavaScript": "js", "TypeScript": "ts",
    }.get(language, "txt")


def path_for(s: Submission) -> Path:
    category = safe(primary_tag(s.tags))
    difficulty = safe(s.difficulty or "Unknown")
    folder = ROOT / s.platform / safe(s.language) / category / difficulty
    return folder / f"{safe(s.problem_id)}-{safe(s.title)}.{extension(s.language)}"


def write_submission(s: Submission) -> Path:
    path = path_for(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s.source.rstrip() + "\n", encoding="utf-8")
    return path


def update_dashboard(records: dict) -> None:
    total = len(records)
    counts = {x: sum(1 for r in records.values() if r.get("difficulty") == x) for x in ("Easy", "Medium", "Hard")}
    rows = [
        "# DSA Solutions", "",
        "Automated accepted-submission archive for LeetCode, CodeChef and HackerRank.", "",
        "## Progress",
        f"**{total} solved** — Easy: {counts['Easy']} · Medium: {counts['Medium']} · Hard: {counts['Hard']}",
        "", "## Platforms",
    ]
    for platform in ("LeetCode", "CodeChef", "HackerRank"):
        n = sum(1 for r in records.values() if r.get("platform") == platform)
        rows.append(f"- **{platform}:** {n}")
    rows += [
        "", "## Layout", "", "`Platform / Language / Topic / Difficulty / Problem.cpp`", "",
        "The workflow updates this repository automatically when new accepted submissions are found.",
    ]
    (ROOT / "README.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def main() -> None:
    records = load_records()
    submissions = fetch_leetcode()
    added = 0
    for s in submissions:
        if s.key in records:
            continue
        path = write_submission(s)
        records[s.key] = {
            **asdict(s),
            "tags": list(s.tags),
            "source_hash": s.source_hash,
            "solution_path": str(path.relative_to(ROOT)),
        }
        added += 1

    save_records(records)
    update_dashboard(records)
    print(f"LeetCode accepted solutions found: {len(submissions)}; added: {added}")

    if added:
        git("add", ".")
        git("commit", "-m", f"sync: add {added} accepted DSA solution(s)")
        git("push")


if __name__ == "__main__":
    main()
