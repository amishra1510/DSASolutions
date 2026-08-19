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
    req = urllib.request.Request(LEETCODE, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json",
        "Origin": "https://leetcode.com", "Referer": "https://leetcode.com/",
        "x-csrftoken": csrf, "Cookie": f"LEETCODE_SESSION={session}; csrftoken={csrf}",
        "User-Agent": "Mozilla/5.0 DSASolutions/1.1",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"LeetCode HTTP {exc.code}") from exc
    if result.get("errors"):
        raise RuntimeError("LeetCode GraphQL returned an error")
    return result


def fetch_leetcode(limit: int = 100) -> list[Submission]:
    """Read the authenticated user's submission list, then retrieve accepted source code.

    recentAcSubmissionList is public and can return an empty list when submission
    history visibility changes. submissionList is authenticated and is therefore
    the reliable source for this sync job.
    """
    status = leetcode_request("""query { userStatus { isSignedIn username } }""")
    user = (status.get("data") or {}).get("userStatus") or {}
    if not user.get("isSignedIn") or not user.get("username"):
        raise RuntimeError("LeetCode authentication rejected or username unavailable")

    query = """query submissions($offset: Int!, $limit: Int!, $lastKey: String, $questionSlug: String) {
      submissionList(offset: $offset, limit: $limit, lastKey: $lastKey, questionSlug: $questionSlug) {
        lastKey
        hasNext
        submissions {
          id
          statusDisplay
          lang
          timestamp
        }
      }
    }"""
    result = leetcode_request(query, {"offset": 0, "limit": limit, "lastKey": None, "questionSlug": None})
    listing = ((result.get("data") or {}).get("submissionList") or {})
    items = listing.get("submissions") or []
    print(f"LeetCode authenticated user: {user['username']}")
    print(f"LeetCode submission records returned: {len(items)}")

    out: list[Submission] = []
    detail_query = """query details($id: Int!) {
      submissionDetails(submissionId: $id) {
        code timestamp statusCode
        lang { name }
        question { questionId title difficulty topicTags { name } }
      }
    }"""
    for item in items:
        if str(item.get("statusDisplay", "")).lower() != "accepted":
            continue
        detail = ((leetcode_request(detail_query, {"id": int(item["id"])}).get("data") or {}).get("submissionDetails") or {})
        if detail.get("statusCode") != 10 or not detail.get("code"):
            continue
        q = detail.get("question") or {}
        tags = tuple(t["name"] for t in q.get("topicTags") or [] if t.get("name"))
        out.append(Submission(
            platform="LeetCode", problem_id=str(q.get("questionId") or item["id"]),
            title=q.get("title") or "Unknown",
            language=canonical_language((detail.get("lang") or {}).get("name") or item.get("lang") or "Unknown"),
            source=detail["code"], accepted_at=str(detail.get("timestamp") or item.get("timestamp") or ""),
            difficulty=q.get("difficulty") if q.get("difficulty") in {"Easy", "Medium", "Hard"} else None,
            tags=tags, submission_id=str(item["id"]),
        ))
    return out


def canonical_language(value: str) -> str:
    return {"cpp": "C++", "c++": "C++", "python3": "Python", "javascript": "JavaScript"}.get(value.lower(), value)


def primary_tag(tags: tuple[str, ...]) -> str:
    priority = ["Array", "String", "Hash Table", "Two Pointers", "Binary Search", "Linked List", "Stack", "Queue", "Tree", "Graph", "Dynamic Programming", "Greedy", "Backtracking", "Heap", "Sorting"]
    lower = {x.lower() for x in tags}
    return next((x for x in priority if x.lower() in lower), tags[0] if tags else "Other")


def safe(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip()
    return re.sub(r"\s+", "-", value)[:100] or "Unknown"


def extension(language: str) -> str:
    return {"C++": "cpp", "C": "c", "Python": "py", "Java": "java", "JavaScript": "js"}.get(language, "txt")


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
    rows = ["# DSA Solutions", "", "Automated accepted-submission archive for LeetCode, CodeChef and HackerRank.", "", "## Progress", f"**{total} solved** — Easy: {counts['Easy']} · Medium: {counts['Medium']} · Hard: {counts['Hard']}", "", "## Platforms"]
    for platform in ("LeetCode", "CodeChef", "HackerRank"):
        n = sum(1 for r in records.values() if r.get("platform") == platform)
        rows.append(f"- **{platform}:** {n}")
    rows += ["", "## Layout", "", "`Platform / Language / Topic / Difficulty / Problem.cpp`", "", "The workflow updates this repository automatically when new accepted submissions are found."]
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
        records[s.key] = {**asdict(s), "tags": list(s.tags), "source_hash": s.source_hash, "solution_path": str(path.relative_to(ROOT))}
        added += 1
    save_records(records)
    update_dashboard(records)
    print(f"LeetCode accepted submissions found: {len(submissions)}; added: {added}")
    if added:
        git("add", ".")
        git("commit", "-m", f"sync: add {added} accepted DSA solution(s)")
        git("push")

if __name__ == "__main__":
    main()
