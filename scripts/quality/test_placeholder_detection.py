import re, sys
from pathlib import Path

_PLACEHOLDER_LEAK_RE = re.compile(
    r"\{PLACEHOLDER_\d+\}"
    r"|\{[A-Z_]{4,}\d*\}"
    r"|\{[\u0600-\u06FF\u064B-\u065F\u0670]{2,}\}",
    re.UNICODE,
)

def detect(target_text):
    body_start = target_text.find("\n---\n", target_text.find("---"))
    body = target_text[body_start:] if body_start != -1 else target_text
    return list(dict.fromkeys(_PLACEHOLDER_LEAK_RE.findall(body)))

content_root = Path("c:/Users/prora/OneDrive/Documents/GitHub/aspose.org/content/reference.aspose.org")
by_lang = {}
for md in content_root.rglob("*.md"):
    lang = md.parts[md.parts.index("reference.aspose.org") + 1] if "reference.aspose.org" in md.parts else "?"
    if lang == "en":
        continue
    try:
        leaks = detect(md.read_text(encoding="utf-8"))
        if leaks:
            by_lang[lang] = by_lang.get(lang, 0) + 1
    except Exception:
        pass

total = sum(by_lang.values())
sys.stdout.buffer.write(f"Total files with placeholder leakage: {total}\n".encode("utf-8"))
for lang, cnt in sorted(by_lang.items(), key=lambda x: -x[1])[:20]:
    sys.stdout.buffer.write(f"  {lang}: {cnt}\n".encode("utf-8"))
