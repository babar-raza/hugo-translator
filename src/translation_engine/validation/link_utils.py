"""Shared markdown link-extraction regex for validators that count/compare links.

VA-04 (TC-APT-105 audit): `LinkValidator._extract_links` and
`StructureValidator._count_links` independently implemented slightly
different regexes -- `LinkValidator` permitted empty anchor text/URL
(`[^\\]]*`/`[^)]*`), `StructureValidator` required non-empty (`[^\\]]+`/`[^)]+`).
A legitimate empty-alt image (``![](image.png)``, a common, valid markdown
construct) matches the permit-empty form but not the require-non-empty one,
so the two validators could silently disagree on a real page's link/image
count. Both now import this single pattern so they can never diverge again.
"""
import re

#: Matches `[text](url)` and `![alt](url)`, permitting empty anchor text
#: and/or empty URL (e.g. `![](image.png)`, a legitimate empty-alt image).
MARKDOWN_LINK_RE = re.compile(r"!?\[([^\]]*)\]\(([^)]*)\)")


def extract_markdown_links(text: str) -> list[tuple[str, str]]:
    """Return every `(anchor_text, url)` pair found in `text`, in order."""
    return [(anchor.strip(), url.strip()) for anchor, url in MARKDOWN_LINK_RE.findall(text)]
