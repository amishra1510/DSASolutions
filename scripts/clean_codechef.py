from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CODECHEF = ROOT / "CodeChef"


def clean_source(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # CodeChef's rendered source container currently includes UI metadata
    # followed by the visible line numbers before the real source begins.
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.fullmatch(r"Language\s*:\s*.+", lines[0].strip(), re.I):
        lines.pop(0)
    while lines and re.fullmatch(r"\d+", lines[0].strip()):
        lines.pop(0)

    return "\n".join(lines).strip() + "\n"


def main():
    if not CODECHEF.exists():
        return

    changed = 0
    for path in CODECHEF.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".c", ".cpp", ".cc", ".cxx", ".java", ".py", ".js", ".ts", ".go", ".rs", ".rb", ".kt"}:
            continue
        old = path.read_text(encoding="utf-8")
        new = clean_source(old)
        if new != old:
            path.write_text(new, encoding="utf-8")
            changed += 1
            print(f"Cleaned: {path.relative_to(ROOT)}")

    print(f"CodeChef files cleaned: {changed}")
    if changed:
        subprocess.run(["git", "add", "CodeChef"], cwd=ROOT, check=True)
        subprocess.run(["git", "commit", "-m", f"fix: clean {changed} CodeChef source file(s)"], cwd=ROOT, check=True)
        subprocess.run(["git", "push"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
