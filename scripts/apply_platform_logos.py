from pathlib import Path

SVG = Path(__file__).resolve().parents[1] / "assets" / "dashboard.svg"

replacements = {
    '<rect x="88" y="443" width="64" height="64" rx="16" fill="#ff7a18"/><text x="120" y="485" text-anchor="middle" font-family="Arial" font-size="32" font-weight="700" fill="#fff">L</text>':
        '<rect x="88" y="443" width="64" height="64" rx="16" fill="#171717" stroke="#ff7a18"/><image href="https://cdn.simpleicons.org/leetcode/ffffff" x="104" y="459" width="32" height="32"/>',
    '<rect x="88" y="687" width="64" height="64" rx="16" fill="#a855f7"/><text x="120" y="729" text-anchor="middle" font-family="Arial" font-size="32" font-weight="700" fill="#fff">C</text>':
        '<rect x="88" y="687" width="64" height="64" rx="16" fill="#171717" stroke="#a855f7"/><image href="https://cdn.simpleicons.org/codechef/ffffff" x="104" y="703" width="32" height="32"/>',
    '<rect x="88" y="931" width="64" height="64" rx="16" fill="#34d399"/><text x="120" y="973" text-anchor="middle" font-family="Arial" font-size="32" font-weight="700" fill="#fff">H</text>':
        '<rect x="88" y="931" width="64" height="64" rx="16" fill="#171717" stroke="#34d399"/><image href="https://cdn.simpleicons.org/hackerrank/ffffff" x="104" y="947" width="32" height="32"/>',
}

text = SVG.read_text(encoding="utf-8")
for old, new in replacements.items():
    text = text.replace(old, new)
SVG.write_text(text, encoding="utf-8")
print("Applied platform logos.")
