import pytest

from src.workers.content_commit_title import content_commit_title
from src.workers.git_provenance import governed_subject_pattern


def test_family_platform_title_and_historical_provenance():
    paths = [
        "content/docs.aspose.org/de/3d/java/page.md",
        "content/docs.aspose.org/fr/3d/java/other.md",
    ]
    summary = "zero-defect shard w1:docs.aspose.org:3d:java:de:1"
    assert content_commit_title(paths, summary) == f"content(3d/java): {summary}"
    pattern = governed_subject_pattern(
        wave=1, site_id="docs.aspose.org", family="3d", platform="java", locale="de"
    )
    assert pattern.fullmatch(content_commit_title(paths, summary))
    assert pattern.fullmatch(f"content(locale): {summary}")
    assert not pattern.fullmatch(f"content(pdf/python): {summary}")


@pytest.mark.parametrize(
    "paths",
    [
        [],
        ["content/docs.aspose.org/de/3d/_index.md"],
        ["content/docs.aspose.org/de/_index.md"],
        ["content/docs.aspose.org/de/3d/java/a.md", "content/docs.aspose.org/de/pdf/python/b.md"],
    ],
)
def test_ambiguous_batch_refused(paths):
    with pytest.raises(ValueError):
        content_commit_title(paths, "translate")


def test_title_cannot_inject_message_trailers():
    with pytest.raises(ValueError):
        content_commit_title(
            ["content/docs.aspose.org/de/3d/java/a.md"], "translate\n\nInjected: x"
        )
