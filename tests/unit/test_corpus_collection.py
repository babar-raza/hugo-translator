"""Test corpus collection for both localization patterns."""

import pytest
from pathlib import Path
from scripts.analyze_ast_corpus import collect_english_files, identify_site_localization_pattern


class TestCorpusCollection:
    """Test file collection from different site patterns."""

    def test_directory_based_collection(self, tmp_path):
        """Test collection from directory-based sites."""
        # Setup: kb.aspose.net/slides/en/file.md
        en_dir = tmp_path / "kb.aspose.net" / "slides" / "en"
        en_dir.mkdir(parents=True)
        (en_dir / "feature.md").write_text("# Feature")
        (en_dir / "guide.md").write_text("# Guide")

        # Also create non-English (should be ignored)
        de_dir = tmp_path / "kb.aspose.net" / "slides" / "de"
        de_dir.mkdir(parents=True)
        (de_dir / "feature.md").write_text("# Funktion")

        files = collect_english_files(tmp_path)
        assert len(files) == 2
        assert all("en" in str(f) for f in files)

    def test_file_based_collection(self, tmp_path):
        """Test collection from file-based sites (blog)."""
        # Setup: blog.aspose.net/post/index.md + index.es.md
        post_dir = tmp_path / "blog.aspose.net" / "2024" / "01" / "my-post"
        post_dir.mkdir(parents=True)
        (post_dir / "index.md").write_text("# English Post")
        (post_dir / "index.es.md").write_text("# Spanish Post")
        (post_dir / "index.de.md").write_text("# German Post")

        files = collect_english_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "index.md"

    def test_mixed_sites(self, tmp_path):
        """Test collection from mixed site patterns."""
        # Directory-based
        kb_dir = tmp_path / "kb.aspose.net" / "slides" / "en"
        kb_dir.mkdir(parents=True)
        (kb_dir / "feature.md").write_text("# Feature")

        # File-based
        blog_dir = tmp_path / "blog.aspose.net" / "post"
        blog_dir.mkdir(parents=True)
        (blog_dir / "index.md").write_text("# Post")
        (blog_dir / "index.es.md").write_text("# Publicacion")

        files = collect_english_files(tmp_path)
        assert len(files) == 2

    def test_identify_pattern_directory(self, tmp_path):
        """Test pattern identification for directory-based sites."""
        site_dir = tmp_path / "kb.aspose.net"
        (site_dir / "slides" / "en").mkdir(parents=True)

        pattern = identify_site_localization_pattern(site_dir)
        assert pattern == "directory"

    def test_identify_pattern_file(self, tmp_path):
        """Test pattern identification for file-based sites."""
        site_dir = tmp_path / "blog.aspose.net"
        post_dir = site_dir / "post"
        post_dir.mkdir(parents=True)
        (post_dir / "index.md").write_text("# Post")
        (post_dir / "index.es.md").write_text("# Publicacion")

        pattern = identify_site_localization_pattern(site_dir)
        assert pattern == "file"

    def test_section_index_files(self, tmp_path):
        """Test that _index.md files are also collected."""
        blog_dir = tmp_path / "blog.aspose.net" / "category"
        blog_dir.mkdir(parents=True)
        (blog_dir / "_index.md").write_text("# Category Index")
        (blog_dir / "index.md").write_text("# Main")

        files = collect_english_files(tmp_path)
        assert len(files) == 2
        file_names = [f.name for f in files]
        assert "_index.md" in file_names
        assert "index.md" in file_names

    def test_excludes_localized_index_files(self, tmp_path):
        """Test that index.{lang}.md files are excluded."""
        blog_dir = tmp_path / "blog.aspose.net" / "post"
        blog_dir.mkdir(parents=True)
        (blog_dir / "index.md").write_text("# English")
        (blog_dir / "index.es.md").write_text("# Spanish")
        (blog_dir / "index.de.md").write_text("# German")
        (blog_dir / "index.fr.md").write_text("# French")
        (blog_dir / "index.zh.md").write_text("# Chinese")

        files = collect_english_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "index.md"

    def test_site_filtering(self, tmp_path):
        """Test that site filtering works."""
        # Create two sites
        kb_dir = tmp_path / "kb.aspose.net" / "slides" / "en"
        kb_dir.mkdir(parents=True)
        (kb_dir / "feature.md").write_text("# Feature")

        products_dir = tmp_path / "products.aspose.net" / "slides" / "en"
        products_dir.mkdir(parents=True)
        (products_dir / "overview.md").write_text("# Overview")

        # Filter to only kb.aspose.net
        files = collect_english_files(tmp_path, sites=["kb.aspose.net"])
        assert len(files) == 1
        assert "kb.aspose.net" in str(files[0])

    def test_empty_directory(self, tmp_path):
        """Test handling of empty directories."""
        # Create empty site directory
        (tmp_path / "kb.aspose.net").mkdir()

        files = collect_english_files(tmp_path)
        assert len(files) == 0

    def test_no_markdown_files(self, tmp_path):
        """Test handling when no markdown files exist."""
        # Create site with only non-markdown files
        site_dir = tmp_path / "kb.aspose.net" / "slides" / "en"
        site_dir.mkdir(parents=True)
        (site_dir / "image.png").write_text("fake image")
        (site_dir / "data.json").write_text("{}")

        files = collect_english_files(tmp_path)
        assert len(files) == 0
