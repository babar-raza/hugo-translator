"""
End-to-end tests for HP fixes in translation pipeline.

These tests translate actual documents and verify structure preservation.
"""

import pytest
from pathlib import Path

from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.extractor import SegmentExtractor
from src.translation_engine.models import TranslationStats
from src.utils.config_loader import ConfigService
from src.tm import TranslationMemory, L1Cache, L2PersistentTM
from src.model_runtime import ModelLoader, ModelRegistry
from src.translation_engine.engine import TranslationEngine


@pytest.fixture(scope="module")
def hp_test_corpus():
    """Path to HP validation test corpus."""
    return Path('tests/fixtures/hp_validation/en')


@pytest.fixture(scope="module")
def config_root():
    """Configuration root directory."""
    return Path(__file__).parent.parent.parent / "config"


@pytest.fixture(scope="module")
def config_service(config_root):
    """Configuration service."""
    return ConfigService(config_root)


@pytest.fixture(scope="module")
def translation_engine(config_service, config_root):
    """Translation engine with full pipeline."""
    # Initialize TM (minimal for testing)
    tm_data_dir = config_root.parent / "data" / "tm"
    tm_data_dir.mkdir(parents=True, exist_ok=True)

    l1_cache = L1Cache(max_size=1000)
    l2_path = tm_data_dir / "l2_lmdb"
    l2_path.mkdir(parents=True, exist_ok=True)
    l2_persistent = L2PersistentTM(str(l2_path))

    tm = TranslationMemory(
        l1_cache=l1_cache,
        l2_persistent=l2_persistent,
        l3_semantic=None
    )

    # Initialize model loader
    registry_path = config_root / "model_registry.yaml"
    model_registry = ModelRegistry(registry_path)

    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        device = "cpu"

    model_loader = ModelLoader(registry=model_registry, device=device)

    # Create engine
    return TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=model_loader
    )


@pytest.fixture(scope="module")
def site_profile(config_service):
    """Site configuration."""
    return config_service.get_site_profile('kb.aspose.net')


class TestHPEndToEnd:
    """End-to-end tests for HP fixes."""

    def _translate_content(self, source_text, translation_engine, site_profile):
        """Helper to translate content using engine's internal API."""
        parser = HugoParser()
        parsed = parser.parse_string(source_text)

        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(parsed, 'en')
        stats = TranslationStats()

        return translation_engine._translate_to_language(
            site_id='kb.aspose.net',
            site_profile=site_profile,
            doc=parsed,
            segments=segments,
            source_lang='en',
            target_lang='de',
            force=False,
            stats=stats
        )

    def test_hp01_lists_preserved_e2e(self, hp_test_corpus, translation_engine, site_profile):
        """HP-01: Lists preserved in actual translation."""

        source_file = hp_test_corpus / '01_lists.md'
        source_text = source_file.read_text(encoding='utf-8')

        translated = self._translate_content(source_text, translation_engine, site_profile)

        # Count list markers
        source_ordered = source_text.count('\n1.') + source_text.count('\n2.') + source_text.count('\n3.')
        source_bullets = source_text.count('\n- ')

        trans_ordered = translated.count('\n1.') + translated.count('\n2.') + translated.count('\n3.')
        trans_bullets = translated.count('\n- ')

        assert trans_ordered == source_ordered, \
            f"Ordered lists: {source_ordered} -> {trans_ordered}"
        assert trans_bullets == source_bullets, \
            f"Bullet lists: {source_bullets} -> {trans_bullets}"

    def test_hp02_links_preserved_e2e(self, hp_test_corpus, translation_engine, site_profile):
        """HP-02: Links with URLs preserved in actual translation."""

        source_file = hp_test_corpus / '02_links.md'
        source_text = source_file.read_text(encoding='utf-8')

        translated = self._translate_content(source_text, translation_engine, site_profile)

        # Verify URLs preserved
        assert 'https://docs.aspose.net/slides/' in translated
        assert 'https://reference.aspose.net/slides/' in translated
        assert 'https://www.nuget.org/packages/' in translated

        # Verify link syntax preserved
        source_links = source_text.count('](')
        trans_links = translated.count('](')

        assert trans_links == source_links, \
            f"Links: {source_links} -> {trans_links}"

    def test_hp02_bold_preserved_e2e(self, hp_test_corpus, translation_engine, site_profile):
        """HP-02: Bold markers preserved in actual translation."""

        source_file = hp_test_corpus / '03_formatting.md'
        source_text = source_file.read_text(encoding='utf-8')

        translated = self._translate_content(source_text, translation_engine, site_profile)

        # Count bold markers
        source_bold = source_text.count('**') // 2
        trans_bold = translated.count('**') // 2

        assert trans_bold == source_bold, \
            f"Bold markers: {source_bold} -> {trans_bold}"

    def test_hp04_terminology_e2e(self, hp_test_corpus, translation_engine, site_profile):
        """HP-04: Terminology protected in actual translation."""

        source_file = hp_test_corpus / '04_terminology.md'
        source_text = source_file.read_text(encoding='utf-8')

        translated = self._translate_content(source_text, translation_engine, site_profile)

        # Verify protected terms NOT translated
        assert 'Aspose.Slides' in translated, "Brand name should be preserved"
        assert '.NET Framework' in translated, "Platform name should be preserved"
        assert 'NuGet' in translated, "Technical term should be preserved"

        # Verify NO corruption
        assert 'Asposa' not in translated, "Brand name should not be corrupted"

    def test_mixed_content_e2e(self, hp_test_corpus, translation_engine, site_profile):
        """All HP fixes work together in complex document."""

        source_file = hp_test_corpus / '05_mixed.md'
        source_text = source_file.read_text(encoding='utf-8')

        translated = self._translate_content(source_text, translation_engine, site_profile)

        # Lists preserved
        assert '\n1.' in translated
        assert '\n- ' in translated

        # Links preserved
        assert '](https://reference.aspose.net/)' in translated

        # Bold preserved
        assert '**' in translated

        # Terminology preserved
        assert 'Presentation' in translated
        assert 'Aspose.Slides' in translated
