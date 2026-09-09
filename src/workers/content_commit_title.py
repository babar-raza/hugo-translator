"""Deterministic family/platform titles for governed content batches."""

import re
from pathlib import PurePosixPath


def content_scope(paths):
    scopes = set()
    for path in paths:
        parts = PurePosixPath(str(path).replace("\\", "/")).parts
        try:
            start = parts.index("content")
        except ValueError as exc:
            raise ValueError(f"content root missing: {path}") from exc
        tail = parts[start + 1 :]
        if len(tail) < 5 or not tail[0].endswith(".aspose.org"):
            raise ValueError(f"cannot derive family/platform from {path}")
        family, platform = tail[2:4]
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
