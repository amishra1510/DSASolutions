from pathlib import Path
import re

SVG = Path(__file__).resolve().parents[1] / "assets" / "dashboard.svg"

# Keep the dashboard simple and reliable: use platform initials instead of
# logo images. This prevents broken-image icons in GitHub README rendering.
platforms = {
    "LeetCode": ("L", "#ff7a18"),
    "CodeChef": ("C", "#a855f7"),
    "HackerRank": ("H", "#34d399"),
}

text = SVG.read_text(encoding="utf-8")

for platform, (letter, color) in platforms.items():
    pattern = rf'<svg x="88" y="(\d+)" width="64" height="64"[^>]*aria-label="{re.escape(platform)} logo">.*?</svg>'

    def replace_logo(match: re.Match) -> str:
        y = match.group(1)
        text_y = int(y) + 42
        return (
            f'<rect x="88" y="{y}" width="64" height="64" rx="16" fill="{color}"/>'
            f'<text x="120" y="{text_y}" text-anchor="middle" '
            f'font-family="Arial" font-size="32" font-weight="700" fill="#fff">{letter}</text>'
        )

    text = re.sub(pattern, replace_logo, text, flags=re.DOTALL)

# Remove any old thick left-side accent bars if they exist.
text = re.sub(r'<rect x="51" y="(406|650|894)" width="7" height="218" rx="4" fill="#[0-9a-fA-F]+"/>', "", text)

SVG.write_text(text, encoding="utf-8")
print("Using L/C/H platform initials and cleaned platform card accents.")
