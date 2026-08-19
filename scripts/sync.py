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
    return json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}

def save_records(records: dict) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def make_session() -> requests.Session:
    session_cookie = os.environ.get("LEETCODE_SESSION")
    csrf = os.environ.get("LEETCODE_CSRF_TOKEN")
    if not session_cookie or not csrf:
        raise RuntimeError("Missing LEETCODE_SESSION or LEETCODE_CSRF_TOKEN")
    s = requests.Session()
    s.headers.update({"Accept":"application/json","Content-Type":"application/json","Origin":"https://leetcode.com","Referer":"https://leetcode.com/","User-Agent":"Mozilla/5.0 DSASolutions/4.0","X-CSRFToken":csrf})
    s.cookies.set("LEETCODE_SESSION", session_cookie, domain="leetcode.com")
    s.cookies.set("csrftoken", csrf, domain="leetcode.com")
    return s

def gql(session: requests.Session, query: str, variables: dict) -> dict:
    last = None
    for attempt in range(3):
        try:
            r = session.post(GRAPHQL, json={"query":query,"variables":variables}, timeout=30)
            r.raise_for_status()
            payload = r.json()
            if payload.get("errors"):
                raise RuntimeError("; ".join(str(e.get("message","GraphQL error")) for e in payload["errors"]))
            return payload
        except Exception as exc:
            last = exc
            if attempt < 2: time.sleep(2 ** attempt)
    raise RuntimeError(f"LeetCode request failed: {last}")

def verify_login(session: requests.Session) -> str:
    user = ((gql(session,"query { userStatus { isSignedIn username } }",{}).get("data") or {}).get("userStatus") or {})
    if not user.get("isSignedIn") or not user.get("username"):
        raise RuntimeError("LeetCode authentication rejected")
    return user["username"]

def fetch_accepted_questions(session: requests.Session) -> list[dict]:
    # Use the problemset AC filter. This is more stable than userProfileQuestions,
    # whose schema/enum arguments have changed across LeetCode deployments.
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
    questions=[]; skip=0; page_size=2000
    while True:
        result=gql(session,query,{"categorySlug":"","skip":skip,"limit":page_size,"filters":{"status":"AC"}})
        listing=((result.get("data") or {}).get("problemsetQuestionList") or {})
        batch=listing.get("questions") or []; total=int(listing.get("total") or 0)
        questions.extend(batch)
        print(f"LeetCode AC problem page {skip // page_size + 1}: {len(batch)} problems (total: {total})")
        if not batch or skip+len(batch)>=total or len(batch)<page_size: break
        skip += len(batch)
    questions=[q for q in questions if str(q.get("status","")).lower() in {"ac","accepted"}]
    print(f"LeetCode accepted problems found: {len(questions)}")
    return questions

def fetch_latest_accepted_submission(session: requests.Session, slug: str) -> dict | None:
    # submissionList is the authenticated per-problem submission history.
    query="""
    query submissionList($offset: Int!, $limit: Int!, $lastKey: String, $questionSlug: String!) {
      submissionList(offset:$offset, limit:$limit, lastKey:$lastKey, questionSlug:$questionSlug) {
        lastKey hasNext
        submissions { id statusDisplay lang timestamp }
      }
    }
    """
    last_key=None
    for _ in range(5):
        listing=((gql(session,query,{"offset":0,"limit":40,"lastKey":last_key,"questionSlug":slug}).get("data") or {}).get("submissionList") or {})
        for sub in listing.get("submissions") or []:
            if str(sub.get("statusDisplay","")).lower() in {"accepted","ac"}:
                return sub
        if not listing.get("hasNext") or not listing.get("lastKey"): break
        last_key=listing["lastKey"]
    return None

def fetch_submission_source(session: requests.Session, submission_id: int) -> dict | None:
    query="""
    query submissionDetails($submissionId: Int!) {
      submissionDetails(submissionId:$submissionId) { code timestamp statusCode lang { name langSlug } }
    }
    """
    return ((gql(session,query,{"submissionId":submission_id}).get("data") or {}).get("submissionDetails") or None)

def canonical_language(value:str)->str:
    return {"cpp":"C++","c++":"C++","python":"Python","python3":"Python","javascript":"JavaScript","typescript":"TypeScript","java":"Java","c":"C","csharp":"C#","golang":"Go","rust":"Rust"}.get(value.lower(),value)

def primary_tag(tags:tuple[str,...])->str:
    priority=["Array","String","Hash Table","Two Pointers","Binary Search","Linked List","Stack","Queue","Tree","Graph","Dynamic Programming","Greedy","Backtracking","Heap","Sorting","Math","Bit Manipulation"]
    lower={x.lower() for x in tags}
    return next((x for x in priority if x.lower() in lower),tags[0] if tags else "Other")

def safe(value:str)->str:
    return re.sub(r"\s+","-",re.sub(r"[^A-Za-z0-9._ -]+","",value).strip())[:100] or "Unknown"

def extension(language:str)->str:
    return {"C++":"cpp","C":"c","Python":"py","Java":"java","JavaScript":"js","TypeScript":"ts","Go":"go","Rust":"rs"}.get(language,"txt")

def path_for(s:Submission)->Path:
    return ROOT/s.platform/safe(s.language)/safe(primary_tag(s.tags))/safe(s.difficulty or "Unknown")/f"{safe(s.problem_id)}-{safe(s.title)}.{extension(s.language)}"

def write_submission(s:Submission)->Path:
    path=path_for(s); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(s.source.rstrip()+"\n",encoding="utf-8"); return path

def update_dashboard(records:dict)->None:
    counts={d:sum(1 for r in records.values() if r.get("difficulty")==d) for d in ("Easy","Medium","Hard")}
    rows=["# DSA Solutions","","Automated accepted-submission archive for LeetCode, CodeChef and HackerRank.","","## Progress",f"**{len(records)} solved** — Easy: {counts['Easy']} · Medium: {counts['Medium']} · Hard: {counts['Hard']}","","## Platforms"]
    for p in ("LeetCode","CodeChef","HackerRank"): rows.append(f"- **{p}:** {sum(1 for r in records.values() if r.get('platform')==p)}")
    rows += ["","## Layout","","`Platform / Language / Topic / Difficulty / Problem.cpp`","","New accepted submissions are synced automatically by GitHub Actions."]
    (ROOT/"README.md").write_text("\n".join(rows)+"\n",encoding="utf-8")

def git(*args:str)->None: subprocess.run(["git",*args],cwd=ROOT,check=True)

def main()->None:
    records=load_records(); session=make_session(); username=verify_login(session)
    print(f"LeetCode authenticated user: {username}")
    questions=fetch_accepted_questions(session); found=0; added=0
    for index,q in enumerate(questions,1):
        slug=q.get("titleSlug")
        if not slug: continue
        try:
            sub=fetch_latest_accepted_submission(session,slug)
            if not sub: print(f"[{index}/{len(questions)}] {slug}: no accepted submission returned"); continue
            detail=fetch_submission_source(session,int(sub["id"]))
            if not detail or not detail.get("code"): print(f"[{index}/{len(questions)}] {slug}: source unavailable"); continue
            language=canonical_language((detail.get("lang") or {}).get("name") or sub.get("lang") or "Unknown")
            tags=tuple(t.get("name") for t in q.get("topicTags") or [] if t.get("name")); difficulty=q.get("difficulty") if q.get("difficulty") in {"Easy","Medium","Hard"} else None
            s=Submission("LeetCode",str(q.get("frontendQuestionId") or slug),q.get("title") or slug,slug,language,detail["code"],str(detail.get("timestamp") or sub.get("timestamp") or ""),difficulty,tags,str(sub["id"]))
            found+=1
            if s.key in records: print(f"[{index}/{len(questions)}] {slug}: already synced"); continue
            path=write_submission(s); records[s.key]={**asdict(s),"tags":list(s.tags),"source_hash":s.source_hash,"solution_path":str(path.relative_to(ROOT))}; added+=1
            print(f"[{index}/{len(questions)}] {slug}: synced -> {path.relative_to(ROOT)}")
        except Exception as exc: print(f"[{index}/{len(questions)}] {slug}: ERROR: {exc}")
    save_records(records); update_dashboard(records); print(f"LeetCode accepted solutions found: {found}; added: {added}")
    if added: git("add","."); git("commit","-m",f"sync: add {added} accepted LeetCode solution(s)"); git("push")

if __name__=="__main__": main()
