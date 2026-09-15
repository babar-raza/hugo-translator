import subprocess

import pytest

from src.observability.git_commit import GitCommitConfig, GitCommitter
from src.workers.content_commit_title import content_commit_title
from src.workers.autonomous_content_translation_worker import AutonomousContentTranslationWorker
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


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "content/blog.aspose.org/pdf/java/pdf-facades-in-java/index.de.md",
            "content(pdf/java): translate",
        ),
        (
            "content/reference.aspose.org/de/cells/go/Font.md",
            "content(cells/go): translate",
        ),
    ],
)
def test_title_uses_family_platform_for_suffix_and_locale_directory_layouts(path, expected):
    assert content_commit_title([path], "translate") == expected


def test_autonomous_worker_commit_title_refuses_mixed_scope():
    first = type("File", (), {"outputs": {"de": "content/docs.aspose.org/de/3d/java/a.md"}})()
    second = type("File", (), {"outputs": {"fr": "content/docs.aspose.org/fr/pdf/python/b.md"}})()
    result = type("Result", (), {"file_results": [first, second]})()
    with pytest.raises(ValueError, match="partition mixed"):
        AutonomousContentTranslationWorker._content_commit_title(result)


def test_generated_title_and_governed_trailer_commit_locally_without_push(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    path = repo / "content/docs.aspose.org/de/3d/java/page.md"
    path.parent.mkdir(parents=True)
    path.write_text("translated", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    title = content_commit_title([path], "translate 1 validated page(s)")
    config = GitCommitConfig(auto_push=False, co_author_name="Codex", co_author_email="codex@example.invalid")
    committer = GitCommitter(config)
    commit_hash = committer._create_commit(f"{title}\n\nCo-authored-by: Codex <codex@example.invalid>", repo)
    assert commit_hash
    message = subprocess.run(
        ["git", "log", "-1", "--format=%B"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert message.startswith("content(3d/java): translate 1 validated page(s)")
    assert message.count("Co-authored-by:") == 1
