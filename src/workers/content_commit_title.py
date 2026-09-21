"""Deterministic family/platform titles for governed content batches."""

import re
from pathlib import PurePosixPath


_LOCALE_SEGMENT = re.compile(r"[a-z]{2}(?:-[a-z0-9]+)?")


def content_scope(paths):
    scopes = set()
    for path in paths:
        parts = PurePosixPath(str(path).replace("\\", "/")).parts
        try:
            start = parts.index("content")
        except ValueError as exc:
            raise ValueError(f"content root missing: {path}") from exc
        tail = parts[start + 1 :]
        if len(tail) < 4 or not tail[0].endswith(".aspose.org"):
            raise ValueError(f"cannot derive family/platform from {path}")
        # Blog-style output keeps the locale as an ``.xx.md`` suffix:
        #   content/blog.aspose.org/pdf/java/page/index.de.md
        # Docs/reference-style output puts locale before the product scope:
        #   content/docs.aspose.org/de/pdf/java/page.md
        # Treating both layouts as ``tail[2:4]`` was a latent defect: blog
        # commits were grouped as ``java/<page-slug>``.  The path structure,
        # not a site-name allowlist, is the authority so new site profiles use
        # the same safe parser.
        offset = 2 if _LOCALE_SEGMENT.fullmatch(tail[1]) else 1
        # Require family, platform, and at least one path component following
        # the platform.  In particular, ``.../de/3d/_index.md`` has no
        # platform and must fail rather than treating ``_index.md`` as one.
        if len(tail) < offset + 3:
            raise ValueError(f"cannot derive family/platform from {path}")
        family, platform = tail[offset : offset + 2]
        for value in (family, platform):
            if not re.fullmatch(r"[a-z0-9][a-z0-9_.+-]*", value) or value.endswith(".md"):
                raise ValueError(f"invalid family/platform in {path}")
        scopes.add((family, platform))
    if len(scopes) != 1:
        raise ValueError(
            "content batch must have exactly one family/platform; partition mixed batches"
        )
    return next(iter(scopes))


def content_commit_title(paths, summary):
    family, platform = content_scope(paths)
    if not summary.strip() or any(c in summary for c in "\r\n\x00"):
        raise ValueError("commit summary must be a nonempty single line")
    return f"content({family}/{platform}): {summary}"
