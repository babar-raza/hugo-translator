"""TC-APT-089: the shipped-corpus FP sweep must not report a vacuous pass.

Found 2026-09-06: pointing --paths-from at uncommitted output makes the sweep
enumerate zero pairs (it only ever looks at git-tracked content), then print
"distinct FP classes: 0" and exit 0 -- indistinguishable from "swept
everything, found nothing" unless a reader notices "restricted to 0 of N
paths" in the log. A caller checking only the exit code (or the headline
class count) reads this as a clean pass on content that was never examined.
"""

import subprocess

import pytest

from scripts.quality.sweep_shipped_corpus_false_positives import main

pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)


def _init_repo(path):
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def _commit_all(path, message="c"):
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, capture_output=True)


class TestPathsFromVacuousRestriction:
    def test_exits_non_zero_when_every_requested_path_is_dropped(self, tmp_path, capsys):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        source = repo / "content" / "site.org" / "page.md"
        source.parent.mkdir(parents=True)
        source.write_text("# Title\n", encoding="utf-8")
        translated = repo / "content" / "site.org" / "page.fr.md"
        translated.write_text("# Titre\n", encoding="utf-8")
        _commit_all(repo)

        # Not committed -- simulates uncommitted output the caller wants swept.
        uncommitted = repo / "content" / "site.org" / "page.de.md"
        uncommitted.write_text("# Titel\n", encoding="utf-8")

        paths_from = tmp_path / "wanted.txt"
        paths_from.write_text("content/site.org/page.de.md\n", encoding="utf-8")
        out_path = tmp_path / "report.json"

        exit_code = main([
            "--repo", str(repo),
            "--paths-from", str(paths_from),
            "--out", str(out_path),
        ])

        assert exit_code == 1
        assert not out_path.exists()
        captured = capsys.readouterr()
        assert "restricted to 0 of 1 requested paths" in captured.out
        assert "NOT a clean pass" in captured.err

    def test_a_partial_restriction_still_proceeds(self, tmp_path):
        """Only a TOTAL wipeout is refused -- some requested paths existing (even if
        fewer than requested) is a legitimate partial sweep, not a vacuous one."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        source = repo / "content" / "site.org" / "page.md"
        source.parent.mkdir(parents=True)
        source.write_text("# Title\n", encoding="utf-8")
        translated = repo / "content" / "site.org" / "page.fr.md"
        translated.write_text("# Titre\n", encoding="utf-8")
        _commit_all(repo)

        paths_from = tmp_path / "wanted.txt"
        paths_from.write_text(
            "content/site.org/page.fr.md\ncontent/site.org/page.de.md\n", encoding="utf-8"
        )
        out_path = tmp_path / "report.json"

        exit_code = main([
            "--repo", str(repo),
            "--paths-from", str(paths_from),
            "--out", str(out_path),
        ])

        assert exit_code == 0
        assert out_path.exists()

    def test_no_paths_from_restriction_at_all_is_unaffected(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        source = repo / "content" / "site.org" / "page.md"
        source.parent.mkdir(parents=True)
        source.write_text("# Title\n", encoding="utf-8")
        translated = repo / "content" / "site.org" / "page.fr.md"
        translated.write_text("# Titre\n", encoding="utf-8")
        _commit_all(repo)
        out_path = tmp_path / "report.json"

        exit_code = main(["--repo", str(repo), "--out", str(out_path)])

        assert exit_code == 0
        assert out_path.exists()
