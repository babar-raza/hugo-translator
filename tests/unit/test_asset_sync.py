"""Tests for asset synchronization utility (TC-04 / GT-AUDIT-03)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.utils.asset_sync import sync_assets, DEFAULT_ASSET_EXTENSIONS


class TestSyncAssets:
    def test_copies_matching_files(self, tmp_path):
        """Copies files with matching extensions from source to target."""
        src = tmp_path / "en"
        dst = tmp_path / "es"
        src.mkdir()
        (src / "image.png").write_bytes(b"\x89PNG fake")
        (src / "photo.jpg").write_bytes(b"\xff\xd8 fake")

        count = sync_assets(src, dst)
        assert count == 2
        assert (dst / "image.png").exists()
        assert (dst / "photo.jpg").exists()

    def test_preserves_subdirectory_structure(self, tmp_path):
        """Files in subdirs are copied to matching subdirs in target."""
        src = tmp_path / "en"
        (src / "page" / "bundle").mkdir(parents=True)
        (src / "page" / "bundle" / "diagram.svg").write_text("<svg/>")

        count = sync_assets(src, tmp_path / "fr")
        assert count == 1
        assert (tmp_path / "fr" / "page" / "bundle" / "diagram.svg").exists()

    def test_skip_if_exists_same_size(self, tmp_path):
        """Does not overwrite if target exists with same size."""
        src = tmp_path / "en"
        dst = tmp_path / "de"
        src.mkdir()
        dst.mkdir()
        data = b"PNG data"
        (src / "logo.png").write_bytes(data)
        (dst / "logo.png").write_bytes(data)  # same size

        count = sync_assets(src, dst, skip_if_exists=True)
        assert count == 0

    def test_overwrites_if_different_size(self, tmp_path):
        """Overwrites target when size differs."""
        src = tmp_path / "en"
        dst = tmp_path / "de"
        src.mkdir()
        dst.mkdir()
        (src / "logo.png").write_bytes(b"new content longer")
        (dst / "logo.png").write_bytes(b"old")

        count = sync_assets(src, dst, skip_if_exists=True)
        assert count == 1
        assert (dst / "logo.png").read_bytes() == b"new content longer"

    def test_skip_if_exists_false(self, tmp_path):
        """With skip_if_exists=False, always copies."""
        src = tmp_path / "en"
        dst = tmp_path / "de"
        src.mkdir()
        dst.mkdir()
        data = b"same"
        (src / "logo.png").write_bytes(data)
        (dst / "logo.png").write_bytes(data)

        count = sync_assets(src, dst, skip_if_exists=False)
        assert count == 1

    def test_ignores_non_matching_extensions(self, tmp_path):
        """Files with non-asset extensions are not copied."""
        src = tmp_path / "en"
        src.mkdir()
        (src / "index.md").write_text("# Hello")
        (src / "data.json").write_text("{}")
        (src / "logo.png").write_bytes(b"img")

        count = sync_assets(src, tmp_path / "ja")
        assert count == 1  # only logo.png

    def test_custom_extensions(self, tmp_path):
        """Custom extensions filter works."""
        src = tmp_path / "en"
        src.mkdir()
        (src / "a.png").write_bytes(b"img")
        (src / "b.csv").write_text("x,y")

        count = sync_assets(src, tmp_path / "ko", extensions=[".csv"])
        assert count == 1
        assert (tmp_path / "ko" / "b.csv").exists()
        assert not (tmp_path / "ko" / "a.png").exists()

    def test_nonexistent_source_returns_zero(self, tmp_path):
        """Non-existent source dir returns 0, no crash."""
        count = sync_assets(tmp_path / "nope", tmp_path / "dst")
        assert count == 0

    def test_default_extensions_cover_common_types(self):
        """Default extension set includes common web asset types."""
        for ext in (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".pdf"):
            assert ext in DEFAULT_ASSET_EXTENSIONS
