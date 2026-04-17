"""
Tests for the orphan-sweep mechanism that commits translated files left behind
by interrupted worker runs.

The orphan sweep runs at the start of each translation run and uses
`git status --porcelain` to find uncommitted .md files across all configured
content roots, then commits them per-site.
"""
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


# Stub heavy ML deps so the import is fast
def _ensure_stubs():
    for mod in ("ctranslate2", "transformers", "sentence_transformers", "faiss", "lmdb", "pytz"):
        sys.modules.setdefault(mod, types.ModuleType(mod))
    if "torch" not in sys.modules:
        torch_stub = types.ModuleType("torch")
        cuda_stub = types.ModuleType("torch.cuda")
        cuda_stub.is_available = MagicMock(return_value=True)
        cuda_stub.empty_cache = MagicMock()
        torch_stub.cuda = cuda_stub
        sys.modules["torch"] = torch_stub
        sys.modules["torch.cuda"] = cuda_stub


_ensure_stubs()


def _make_worker(sites_config=None):
    """Create a minimal worker with mocked dependencies."""
    from src.workers.autonomous_content_translation_worker import AutonomousContentTranslationWorker

    config = MagicMock()
    config.site = None
    config.max_seconds_per_run = 3600
    config.max_sites_per_run = None

    config_service = MagicMock()

    if sites_config:
        config_service.list_sites.return_value = list(sites_config.keys())
        profiles = {}
        for site_id, roots in sites_config.items():
            profile = MagicMock()
            profile.content_roots = roots
            profile.default_source_lang = "en"
            # output_layout=None ensures _is_translation_output uses filename-suffix
            # detection (index.de.md) rather than per_language_folders detection
            # (lang inferred from folder name). A bare MagicMock is truthy and
            # would incorrectly activate the per_language_folders path.
            profile.output_layout = None
            # Explicit target_langs required: _is_translation_output() checks
            # whether the file's language suffix is in this set.  A bare MagicMock
            # iterates as empty, causing all files to be rejected as "unknown lang".
            profile.target_langs = [
                "de", "fr", "zh", "ar", "es", "pt", "ru", "ja", "ko",
                "it", "nl", "pl", "tr", "sv", "da", "fi", "cs", "sk",
                "hu", "ro", "bg", "hr", "sr", "sl", "uk", "ms", "id",
            ]
            profiles[site_id] = profile
        config_service.get_site_profile.side_effect = lambda sid: profiles[sid]
        config_service.resolve_content_root.side_effect = lambda cr: Path(cr)

        # git_commit config
        gc = MagicMock()
        gc.git_commit = {"enabled": True, "auto_push": True}
        config_service.global_config = gc
    else:
        config_service.list_sites.return_value = []

    with patch.object(AutonomousContentTranslationWorker, '__init__', lambda self, *a, **kw: None):
        worker = AutonomousContentTranslationWorker.__new__(AutonomousContentTranslationWorker)
        worker.config = config
        worker.config_service = config_service

    return worker


class TestOrphanSweep:
    """Tests for _commit_orphaned_translations."""

    def test_no_sites_returns_zero(self):
        worker = _make_worker()
        assert worker._commit_orphaned_translations() == 0

    def test_no_uncommitted_files(self, tmp_path):
        content_root = tmp_path / "content" / "blog.aspose.net"
        content_root.mkdir(parents=True)
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
        )

        worker = _make_worker({"blog.aspose.net": [str(content_root)]})
        result = worker._commit_orphaned_translations()
        assert result == 0

    def test_finds_and_commits_orphaned_files(self, tmp_path):
        """Simulate orphaned .md files and verify they get committed."""
        content_root = tmp_path / "content" / "blog.aspose.net"
        content_root.mkdir(parents=True)

        # Init git repo
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path), capture_output=True,
        )

        # Create orphaned translation files (untracked)
        barcode_dir = content_root / "barcode" / "article1"
        barcode_dir.mkdir(parents=True)
        (barcode_dir / "index.de.md").write_text("---\ntitle: test\n---\nHallo", encoding="utf-8")
        (barcode_dir / "index.zh.md").write_text("---\ntitle: test\n---\nNihao", encoding="utf-8")

        worker = _make_worker({"blog.aspose.net": [str(content_root)]})
        result = worker._commit_orphaned_translations()

        # Recovery counts commits (one per site), not individual files.
        # Both orphaned files are in the same site → 1 commit expected.
        assert result >= 1

        # Verify files are now committed (clean working tree)
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(tmp_path), capture_output=True, text=True,
        )
        assert status.stdout.strip() == ""

    def test_detects_languages_from_filenames(self, tmp_path):
        """Verify language detection and commit message template from file stems."""
        from src.observability.git_commit import GitCommitConfig
        from src.workers.autonomous_content_translation_worker import (
            AutonomousContentTranslationWorker,
        )

        files = [
            Path(tmp_path / "content" / "blog.aspose.net" / "barcode" / "art1" / "index.de.md"),
            Path(tmp_path / "content" / "blog.aspose.net" / "barcode" / "art1" / "index.fr.md"),
            Path(tmp_path / "content" / "blog.aspose.net" / "barcode" / "art1" / "index.zh.md"),
        ]
        config = GitCommitConfig()
        msg = AutonomousContentTranslationWorker._build_orphan_commit_message(
            files, "blog.aspose.net", config,
        )

        # Subject should use blog scope (not product) for content sites
        assert msg.startswith("chore(blog):")
        # Languages detected and listed
        assert "de" in msg
        assert "fr" in msg
        assert "zh" in msg
        # Template fields present
        assert "orphan recovery" in msg
        assert "Run ID: orphan-sweep:blog.aspose.net" in msg
        assert "Site: blog.aspose.net" in msg
        assert "Co-authored-by:" in msg
        # Language breakdown with counts
        assert "de (1)" in msg
        assert "fr (1)" in msg
        assert "zh (1)" in msg

    def test_multi_product_uses_site_scope(self):
        """When files span multiple products, use site-level scope not product."""
        from src.observability.git_commit import GitCommitConfig
        from src.workers.autonomous_content_translation_worker import (
            AutonomousContentTranslationWorker,
        )

        files = [
            Path("D:/repo/content/reference.aspose.net/barcode/ar/api.md"),
            Path("D:/repo/content/reference.aspose.net/slides/ar/api.md"),
            Path("D:/repo/content/reference.aspose.net/words/de/api.md"),
        ]
        config = GitCommitConfig()
        msg = AutonomousContentTranslationWorker._build_orphan_commit_message(
            files, "reference.aspose.net", config,
        )

        # Multi-product → site-level scope "reference", NOT "barcode"
        assert msg.startswith("chore(reference):")
        assert "API references" in msg

    def test_single_product_uses_product_scope(self):
        """When all files are from one product on a doc site, use product scope."""
        from src.observability.git_commit import GitCommitConfig
        from src.workers.autonomous_content_translation_worker import (
            AutonomousContentTranslationWorker,
        )

        files = [
            Path("D:/repo/content/reference.aspose.net/slides/ar/api1.md"),
            Path("D:/repo/content/reference.aspose.net/slides/de/api2.md"),
        ]
        config = GitCommitConfig()
        msg = AutonomousContentTranslationWorker._build_orphan_commit_message(
            files, "reference.aspose.net", config,
        )

        # Single product → product-level scope "slides"
        assert msg.startswith("chore(slides):")

    def test_handles_multiple_sites(self, tmp_path):
        """Orphans from different sites get separate commits."""
        blog_root = tmp_path / "content" / "blog.aspose.net"
        docs_root = tmp_path / "content" / "docs.aspose.net"
        blog_root.mkdir(parents=True)
        docs_root.mkdir(parents=True)

        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path), capture_output=True,
        )

        (blog_root / "post.de.md").write_text("blog de", encoding="utf-8")
        (docs_root / "page.fr.md").write_text("docs fr", encoding="utf-8")

        worker = _make_worker({
            "blog.aspose.net": [str(blog_root)],
            "docs.aspose.net": [str(docs_root)],
        })

        result = worker._commit_orphaned_translations()
        assert result >= 2

        # Two commits should exist (init + blog + docs)
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(tmp_path), capture_output=True, text=True,
        )
        # At least 3 commits: init + 2 site commits
        assert len(log.stdout.strip().splitlines()) >= 3

    def test_disabled_git_commit_skips(self, tmp_path):
        """If git_commit.enabled is false, skip the commit."""
        content_root = tmp_path / "content" / "blog.aspose.net"
        content_root.mkdir(parents=True)

        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path), capture_output=True,
        )

        (content_root / "index.de.md").write_text("test", encoding="utf-8")

        worker = _make_worker({"blog.aspose.net": [str(content_root)]})
        # Disable git commit
        worker.config_service.global_config.git_commit = {"enabled": False}

        result = worker._commit_orphaned_translations()
        assert result == 0

        # File should still be untracked (git shows directory for untracked dirs)
        status = subprocess.run(
            ["git", "status", "--porcelain", str(content_root)],
            cwd=str(tmp_path), capture_output=True, text=True,
        )
        assert status.stdout.strip() != ""  # Still has uncommitted content

    def test_nonexistent_content_root_skipped(self):
        """Content roots that don't exist are silently skipped."""
        worker = _make_worker({
            "missing.site": ["/nonexistent/path/content"],
        })
        result = worker._commit_orphaned_translations()
        assert result == 0
