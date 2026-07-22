"""
HT-QUALITY-GATES-001 Part 26: language-detection gates must not be biased by
deliberately passthrough (mode: passthrough) frontmatter field values.

Real confirmed repro (found while investigating residual title mismatches
after the ms/zh/uk fixes): `testimonialswrapper.tmessage` on
products.aspose.org is a genuine customer quote, deliberately left in its
original language (mode: passthrough). It's long enough that it biased
FastText's whole-file language classification toward English, even though
every actually-translatable field was correctly translated into hr/sr.
This made CASE 1/CASE 4 overwrite-protection block legitimate retranslations
indefinitely, leaving stale pre-mission content (and its wrong title) in
place no matter how many times the file was retranslated.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.translation_engine.write_gate import (
    WriteGateEvaluator,
    _build_language_detection_text,
)
from src.utils.models import FrontmatterMode


def _rule(mode):
    return SimpleNamespace(mode=mode)


def _site_profile():
    return SimpleNamespace(
        frontmatter={
            "title": _rule(FrontmatterMode.TRANSLATE),
            "testimonialswrapper.tmessage": _rule(FrontmatterMode.PASSTHROUGH),
        }
    )


_TESTIMONIAL = (
    "We needed to validate, re-orient, and re-export thousands of OBJ and "
    "GLB assets as part of our CI pipeline. It saved us weeks of custom "
    "parser work."
)

# Real-shape content: title/description genuinely translated to Croatian,
# testimonial correctly left in English (mode: passthrough).
_HR_CONTENT = (
    "---\n"
    "title: Aspose.3D FOSS\n"
    "description: Učitaj, stvori, transformiraj i izvezi 3D scene.\n"
    "testimonialswrapper:\n"
    f"    tmessage: {_TESTIMONIAL}\n"
    "---\nbody\n"
)


class TestBuildLanguageDetectionText:
    def test_passthrough_value_stripped(self):
        result = _build_language_detection_text(_HR_CONTENT, _site_profile())
        assert _TESTIMONIAL not in result

    def test_translated_content_untouched(self):
        result = _build_language_detection_text(_HR_CONTENT, _site_profile())
        assert "Učitaj, stvori, transformiraj i izvezi 3D scene." in result

    def test_no_site_profile_returns_original(self):
        assert _build_language_detection_text(_HR_CONTENT, None) == _HR_CONTENT

    def test_site_profile_without_frontmatter_returns_original(self):
        assert _build_language_detection_text(_HR_CONTENT, SimpleNamespace()) == _HR_CONTENT

    def test_short_passthrough_value_not_stripped(self):
        """Only substantial values are stripped -- a short passthrough
        field (e.g. a URL) isn't what biases whole-file detection."""
        content = (
            "---\ntitle: Test\n"
            "testimonialswrapper:\n    tmessage: Hi\n---\nbody\n"
        )
        result = _build_language_detection_text(content, _site_profile())
        assert "Hi" in result

    def test_translate_mode_fields_never_stripped(self):
        """Only PASSTHROUGH fields are affected -- a long TRANSLATE-mode
        value must survive untouched."""
        long_translated = "A" * 50
        profile = SimpleNamespace(frontmatter={"description": _rule(FrontmatterMode.TRANSLATE)})
        content = f"---\ntitle: Test\ndescription: {long_translated}\n---\nbody\n"
        result = _build_language_detection_text(content, profile)
        assert long_translated in result


class TestOverwriteProtectionPassthroughAware:
    def _make_evaluator(self, det, tracker=None):
        config = MagicMock()
        config.get_config.return_value = {"translation_engine": {}}
        return WriteGateEvaluator(
            detector=det, similarity_tracker=tracker, config=config, force_accept=False
        )

    def test_case4_real_repro_no_longer_blocks_on_testimonial_bias(self, tmp_path):
        """The real confirmed repro: both existing and new full-file text
        detect as 'en' (biased by the long English testimonial), even
        though the actually-translatable content is genuinely correct hr.
        With passthrough-aware detection, both sides should detect
        correctly once the bias is removed. `_gate_overwrite_protection`'s
        `translated_content` param is contractually pre-stripped by its
        caller (`evaluate()`) -- this test mirrors that real call shape
        rather than exercising the raw (unstripped) new-content path, which
        is `evaluate()`'s job, not this gate's."""
        out = tmp_path / "existing.md"
        out.write_text(_HR_CONTENT, encoding="utf-8")

        det = MagicMock()

        def detect(text):
            if _TESTIMONIAL in text:
                return ("en", 0.85)  # whole-file, biased by testimonial
            return ("hr", 0.90)  # testimonial stripped -> genuinely hr

        det.detect.side_effect = detect
        gate = self._make_evaluator(det)

        pre_stripped_new_content = _build_language_detection_text(_HR_CONTENT, _site_profile())

        from src.translation_engine.write_gate import WriteGateResult
        r = WriteGateResult(passed=True)
        gate._gate_overwrite_protection(
            pre_stripped_new_content, "hr", out, det, r, site_profile=_site_profile()
        )

        assert r.passed, "passthrough-aware detection must resolve the real testimonial-bias case"

    def test_case4_without_site_profile_still_blocks_as_before(self, tmp_path):
        """Regression guard: omitting site_profile (e.g. a caller that
        hasn't been updated) must not change behavior -- still detects the
        biased 'en' on both sides and blocks, exactly as before this fix."""
        out = tmp_path / "existing.md"
        out.write_text(_HR_CONTENT, encoding="utf-8")

        det = MagicMock()
        det.detect.return_value = ("en", 0.85)
        gate = self._make_evaluator(det)

        from src.translation_engine.write_gate import WriteGateResult
        r = WriteGateResult(passed=True)
        gate._gate_overwrite_protection(_HR_CONTENT, "hr", out, det, r, site_profile=None)

        assert not r.passed
        assert r.retranslate_queued
