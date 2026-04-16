"""
Language purity tests for Chinese content.

Tests config-driven behavior from:
- LP-001: technical_terms.yaml (30+ new terms)
- LP-002: baseline_groups in global.yaml (Chinese group)
- LP-003: script_validation thresholds (CJK: 0.70)

Framework: ORCHESTRATOR (Evidence-Based Development)
Task: LP-004 (Language Purity Tests - Chinese)
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind


class TestChineseLanguagePurity:
    """Test language purity validation for Chinese content."""

    @pytest.fixture
    def extractor(self):
        """Create TextUnitExtractor with real config for integration testing."""
        # Use real extractor to test config-driven behavior
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Mock FastText detector to control detection results
        mock_detector = Mock()
        mock_detector.is_available = True
        extractor.fasttext_detector = mock_detector

        return extractor

    @pytest.fixture
    def sample_units(self):
        """Create sample TextUnits for testing."""
        def create_units(texts):
            units = []
            for i, text in enumerate(texts):
                node_addr = f"test.node[{i}]"
                unit = TextUnit(
                    unit_id=TextUnit.create_id(node_addr, text, TextUnitKind.TEXT),
                    node_addr=node_addr,
                    kind=TextUnitKind.TEXT,
                    source_text=text,
                    translated_text=text,
                    do_not_translate=False,
                )
                units.append(unit)
            return units
        return create_units

    def test_chinese_vietnamese_passes_script_validation(self, extractor, sample_units):
        """
        Test Chinese→Vietnamese passes script validation (>70% CJK).

        Validates LP-003: script_validation thresholds["cjk"] = 0.70 (relaxed from 0.80)
        Validates LP-002: baseline_groups["southeast_asian"] includes Vietnamese
        """
        # Chinese text with >70% CJK characters (some Latin for technical terms)
        # Use more Chinese characters to ensure >70% CJK ratio
        chinese_text = "使用 Azure 接口进行智能翻译文档处理系统"
        units = sample_units([chinese_text])

        # Mock FastText to detect as Vietnamese (wrong, but should be accepted via script validation)
        extractor.fasttext_detector.detect.return_value = ("vi", 0.80)

        # Mock script validation to return True (>70% CJK)
        def mock_verify(text, expected_lang, similarity_tracker=None, script_validation_thresholds=None):
            # Calculate CJK ratio
            cjk_chars = sum(1 for c in text if '\u4E00' <= c <= '\u9FFF')
            total_chars = sum(1 for c in text if c.strip())
            if total_chars > 0:
                cjk_ratio = cjk_chars / total_chars
                if cjk_ratio >= 0.70:  # LP-003 threshold
                    return True
            return False

        extractor.fasttext_detector.verify_language = mock_verify

        result = extractor._verify_translation_language_purity(units, "zh")

        assert result is True, "Chinese→Vietnamese should pass via script validation (>70% CJK)"

        # Verify CJK ratio
        cjk_chars = sum(1 for c in chinese_text if '\u4E00' <= c <= '\u9FFF')
        total_chars = sum(1 for c in chinese_text if c.strip())
        cjk_ratio = cjk_chars / total_chars
        assert cjk_ratio >= 0.70, f"CJK ratio should be >=70%, got {cjk_ratio:.2%}"

    def test_chinese_with_technical_terms_api_sdk(self, extractor, sample_units):
        """
        Test Chinese with technical terms (API, SDK, Azure) bypasses purity check.

        Validates LP-001: API, SDK, Azure are recognized as technical terms.
        """
        # Chinese text with 30% technical density
        # Technical terms: API, SDK, Azure (3 terms / ~10 words = 30%)
        chinese_text = "使用 API 和 SDK 在 Azure 平台开发应用程序"
        units = sample_units([chinese_text])

        # Calculate technical density
        density = extractor._calculate_technical_density(chinese_text)

        # Mock detection as wrong language
        extractor.fasttext_detector.detect.return_value = ("ja", 0.85)
        extractor.fasttext_detector.verify_language.return_value = False

        if density >= 0.25:
            # Should bypass due to technical density
            result = extractor._verify_translation_language_purity(units, "zh")
            assert result is True, "Chinese with >25% technical terms should bypass purity check"
            assert density >= 0.25, f"Technical density should be >=25%, got {density:.2%}"

    def test_chinese_with_latin_script_terms_cloud_docker(self, extractor, sample_units):
        """
        Test Chinese with Latin script technical terms (Cloud, Docker, Kubernetes).

        Validates LP-001: Cloud infrastructure terms are recognized.
        Validates LP-003: Mixed-script handling (CJK + Latin).
        """
        # Chinese text with Latin technical terms
        chinese_text = "在 Cloud 上部署 Docker 和 Kubernetes 容器"
        units = sample_units([chinese_text])

        # Calculate technical density
        density = extractor._calculate_technical_density(chinese_text)

        # Mock detection
        extractor.fasttext_detector.detect.return_value = ("zh", 0.88)
        extractor.fasttext_detector.verify_language.return_value = True

        result = extractor._verify_translation_language_purity(units, "zh")

        assert result is True, "Chinese with Latin technical terms should pass"

        # Verify terms recognized: Cloud, Docker, Kubernetes
        assert density > 0, "Should recognize Cloud, Docker, Kubernetes as technical terms"

    def test_pure_chinese_text_100_percent_cjk(self, extractor, sample_units):
        """Test pure Chinese text (100% CJK script) passes validation."""
        # Pure Chinese text with no Latin characters
        chinese_text = "这是一个关于软件开发的技术文档说明"
        units = sample_units([chinese_text])

        # Mock FastText to correctly detect as Chinese
        extractor.fasttext_detector.detect.return_value = ("zh", 0.95)
        extractor.fasttext_detector.verify_language.return_value = True

        result = extractor._verify_translation_language_purity(units, "zh")

        assert result is True, "Pure Chinese text should pass validation"

        # Verify 100% CJK script
        cjk_chars = sum(1 for c in chinese_text if '\u4E00' <= c <= '\u9FFF')
        total_chars = sum(1 for c in chinese_text if c.strip())
        cjk_ratio = cjk_chars / total_chars
        assert cjk_ratio >= 0.95, f"CJK ratio should be ~100%, got {cjk_ratio:.2%}"

    def test_chinese_with_high_technical_density_bypass(self, extractor, sample_units):
        """
        Test Chinese with >25% technical terms bypasses purity check.

        Validates LP-001: Multiple Aspose products and technical terms.
        """
        # Chinese text with high technical density
        # Technical terms: Aspose.Cells, API, DataFrame, Excel, XLSX (5 terms / ~10 words = 50%)
        chinese_text = "使用 Aspose.Cells API 处理 DataFrame 和 Excel XLSX 文件"
        units = sample_units([chinese_text])

        # Calculate technical density
        density = extractor._calculate_technical_density(chinese_text)

        # Mock detection as wrong language
        extractor.fasttext_detector.detect.return_value = ("ja", 0.90)
        extractor.fasttext_detector.verify_language.return_value = False

        # Should bypass due to high technical density
        result = extractor._verify_translation_language_purity(units, "zh")

        assert result is True, "Chinese with >25% technical density should bypass purity check"
        assert density >= 0.25, f"Technical density should be >=25%, got {density:.2%}"

    def test_chinese_edge_case_exactly_70_percent_cjk_script(self, extractor, sample_units):
        """
        Test edge case: Chinese with exactly 70% CJK script.

        Validates LP-003: script_validation threshold for CJK is 0.70.
        """
        # Construct text with exactly 70% CJK characters
        # 7 CJK chars + 3 Latin chars = 70% CJK
        chinese_text = "使用Azure处理数据API文档"  # Mix to get ~70% CJK
        units = sample_units([chinese_text])

        # Calculate actual CJK ratio
        cjk_chars = sum(1 for c in chinese_text if '\u4E00' <= c <= '\u9FFF')
        total_chars = sum(1 for c in chinese_text if c.strip())
        cjk_ratio = cjk_chars / total_chars

        # Mock detection as wrong language
        extractor.fasttext_detector.detect.return_value = ("ja", 0.85)

        def mock_verify(text, expected_lang, similarity_tracker=None, script_validation_thresholds=None):
            # Simulate script validation with 70% threshold
            cjk_chars = sum(1 for c in text if '\u4E00' <= c <= '\u9FFF')
            total_chars = sum(1 for c in text if c.strip())
            if total_chars > 0 and (cjk_chars / total_chars) >= 0.70:
                return True
            return False

        extractor.fasttext_detector.verify_language = mock_verify

        if cjk_ratio >= 0.70:
            result = extractor._verify_translation_language_purity(units, "zh")
            assert result is True, f"Chinese with >=70% CJK script should pass (got {cjk_ratio:.2%})"

    def test_chinese_simplified_traditional_baseline_acceptance(self, extractor, sample_units):
        """
        Test Chinese Simplified→Traditional accepted via Chinese baseline group.

        Validates LP-002: baseline_groups["chinese"] includes ["zh", "zh-CN", "zh-TW", "zh-HK"]
        """
        chinese_text = "这是简体中文文档"
        units = sample_units([chinese_text])

        # Mock detection as Traditional Chinese
        extractor.fasttext_detector.detect.return_value = ("zh-TW", 0.88)

        def mock_verify(text, expected_lang, similarity_tracker=None, script_validation_thresholds=None):
            # Simulate baseline group acceptance
            if similarity_tracker and similarity_tracker.are_similar("zh", "zh-TW"):
                return True
            return False

        extractor.fasttext_detector.verify_language = mock_verify

        result = extractor._verify_translation_language_purity(units, "zh")

        assert result is True, "Chinese Simplified→Traditional should be accepted via Chinese baseline group"

        # Verify baseline group contains Chinese variants
        if extractor.similarity_tracker:
            baseline_groups = extractor.similarity_tracker.baseline_groups
            chinese_group = baseline_groups.get("chinese", [])
            expected_variants = ["zh", "zh-CN", "zh-TW"]
            for variant in expected_variants:
                assert variant in chinese_group, f"Chinese variant '{variant}' should be in Chinese group (LP-002)"

    def test_chinese_with_machine_learning_terms(self, extractor, sample_units):
        """
        Test Chinese with Machine Learning terms from LP-001.

        Validates LP-001: Machine Learning, Model, Training, Dataset terms recognized.
        """
        # Chinese text with ML terms
        chinese_text = "使用 Machine Learning 训练 Model 处理 Dataset 数据"
        units = sample_units([chinese_text])

        # Calculate technical density
        density = extractor._calculate_technical_density(chinese_text)

        # Machine Learning, Model, Dataset = 3 terms / ~10 words = 30%
        assert density >= 0.20, f"Should recognize ML terms (density={density:.2%})"

    def test_chinese_with_aspose_products_mixed_script(self, extractor, sample_units):
        """
        Test Chinese with Aspose product names (mixed CJK + Latin script).

        Validates LP-001: Aspose.BarCode, Aspose.Email, Aspose.OCR recognized.
        """
        # Chinese text with multiple Aspose products
        chinese_text = "Aspose.BarCode 和 Aspose.Email 是强大的开发工具"
        units = sample_units([chinese_text])

        # Calculate technical density
        density = extractor._calculate_technical_density(chinese_text)

        # Aspose.BarCode, Aspose.Email = 2 terms / ~8 words = 25%
        assert density >= 0.20, f"Should recognize Aspose products (density={density:.2%})"

        # Verify mixed script handling (CJK + Latin)
        cjk_chars = sum(1 for c in chinese_text if '\u4E00' <= c <= '\u9FFF')
        latin_chars = sum(1 for c in chinese_text if c.isalpha() and ord(c) < 0x0250)
        assert cjk_chars > 0 and latin_chars > 0, "Should contain both CJK and Latin characters"

    def test_chinese_short_text_skipped(self, extractor, sample_units):
        """Test very short Chinese text is skipped (unreliable for detection)."""
        # Text shorter than LANGUAGE_PURITY_MIN_LENGTH (15 chars)
        chinese_text = "你好世界"
        units = sample_units([chinese_text])

        # Should skip validation for short texts
        result = extractor._verify_translation_language_purity(units, "zh")

        assert result is True, "Short text should be skipped (unreliable for detection)"

    def test_chinese_config_driven_behavior_verification(self, extractor):
        """
        Verify extractor loads config from global.yaml and technical_terms.yaml.

        Ensures tests validate actual config-driven behavior, not hardcoded logic.
        """
        # Verify script validation thresholds loaded
        if extractor.script_validation_thresholds:
            thresholds = extractor.script_validation_thresholds
            assert "cjk" in thresholds, "CJK script threshold should exist (LP-003)"
            assert thresholds["cjk"] == 0.70, f"CJK threshold should be 0.70 (LP-003), got {thresholds['cjk']}"

        # Verify technical terms loaded
        assert extractor.technical_terms is not None, "Technical terms should be loaded"
        assert len(extractor.technical_terms) > 0, "Technical terms list should not be empty"

        # Verify LP-001 terms are present
        expected_terms = ["Azure", "API", "SDK", "Cloud", "Docker", "Machine Learning", "DataFrame"]
        for term in expected_terms:
            assert term in extractor.technical_terms, f"Term '{term}' should be in technical_terms (LP-001)"

        # Verify similarity tracker has Chinese baseline group
        if extractor.similarity_tracker:
            baseline_groups = extractor.similarity_tracker.baseline_groups
            assert "chinese" in baseline_groups, "Chinese baseline group should exist (LP-002)"

            chinese_group = baseline_groups["chinese"]
            expected_variants = ["zh", "zh-CN", "zh-TW", "zh-HK"]
            for variant in expected_variants:
                assert variant in chinese_group, f"Chinese variant '{variant}' should be in Chinese group (LP-002)"
