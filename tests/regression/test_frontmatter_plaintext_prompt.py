"""RB-012 (config/review_rubric.yaml): frontmatter string fields (title,
seoTitle, description, summary) are plain text consumed by HTML meta tags,
RSS feeds, and search snippets -- they are never markdown-rendered. Before
this fix, LLMModelBackend._build_batch_system_prompt() had no branch for the
``frontmatter_<field>`` context_hint that segment_translator.py already sets
(and that this method's own docstring names "frontmatter_description" as an
example of), so every frontmatter translation silently fell through to the
generic prompt's "Preserve all formatting: markdown" instruction -- correct
for body text, but an invitation to add markup to a plain-text field.

Reproduced on blog.aspose.org/pdf/python/pdf-generated-in-python: 2 of 8
accepted description-field translations (nl via m2m100_418m, th via
professionalize_llm) came back with technical terms wrapped in bold
("**aspose_pdf.generated**") that were plain prose in the English source.
"""

from unittest.mock import MagicMock

from src.model_runtime.llm_backend import LLMModelBackend, _ctx_hint_var


def _make_backend():
    model_info = MagicMock()
    model_info.system_prompt_template = None
    model_info.llm_provider = "openai_compatible"
    model_info.llm_base_url = "http://test.local/v1"
    model_info.llm_api_key_env = None
    model_info.llm_model_name = "test"
    model_info.llm_temperature = 0.0
    model_info.llm_max_tokens = 6000
    model_info.llm_timeout = 60

    backend = LLMModelBackend(model_info, "cpu")
    backend.loaded = True
    return backend


class TestFrontmatterHintGetsAPlainTextPrompt:
    def test_no_hint_still_preserves_markdown_for_body_text(self):
        """Regression control: the default (body-text) prompt is unchanged."""
        backend = _make_backend()
        prompt = backend._build_batch_system_prompt("en", "de", 3)
        assert "Preserve all formatting: markdown" in prompt

    def test_frontmatter_description_hint_forbids_markdown(self):
        backend = _make_backend()
        token = _ctx_hint_var.set("frontmatter_description")
        try:
            prompt = backend._build_batch_system_prompt("en", "nl", 3)
        finally:
            _ctx_hint_var.reset(token)
        assert "no markdown formatting" in prompt
        assert "**bold**" in prompt  # names the exact defect shape
        assert "Preserve all formatting: markdown" not in prompt

    def test_frontmatter_summary_hint_also_matches(self):
        """Any frontmatter_<field> hint takes this branch, not just description."""
        backend = _make_backend()
        token = _ctx_hint_var.set("frontmatter_summary")
        try:
            prompt = backend._build_batch_system_prompt("en", "th", 2)
        finally:
            _ctx_hint_var.reset(token)
        assert "no markdown formatting" in prompt

    def test_frontmatter_hint_still_protects_technical_identifiers(self):
        backend = _make_backend()
        token = _ctx_hint_var.set("frontmatter_description")
        try:
            prompt = backend._build_batch_system_prompt("en", "ru", 1)
        finally:
            _ctx_hint_var.reset(token)
        assert "technical terms" in prompt.lower()

    def test_api_property_description_hint_is_unaffected(self):
        """Regression control: the pre-existing api_property_description
        branch (which legitimately preserves backtick/markdown formatting
        for API doc content) must not be touched by the new frontmatter_*
        branch ordering."""
        backend = _make_backend()
        token = _ctx_hint_var.set("api_property_description")
        try:
            prompt = backend._build_batch_system_prompt("en", "fr", 4)
        finally:
            _ctx_hint_var.reset(token)
        assert "Preserve backtick spans and markdown formatting" in prompt
        assert "API documentation translator" in prompt
