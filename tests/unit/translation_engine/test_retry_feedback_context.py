from src.translation_engine.segment_translator import _RetryFeedbackModel


def test_retry_feedback_model_forwards_context_with_feedback():
    class Backend:
        def translate_with_context(self, texts, src, target, **kwargs):
            self.call = (texts, src, target, kwargs)
            return ["translated"]

    backend = Backend()
    wrapped = _RetryFeedbackModel(backend, "fix the failed title")

    assert wrapped.translate_with_context(["source"], "en", "cs", context_hint="frontmatter_title") == ["translated"]
    assert backend.call[3]["retry_feedback"] == "fix the failed title"
    assert backend.call[3]["context_hint"] == "frontmatter_title"


def test_retry_feedback_model_defers_to_callers_own_retry_feedback():
    """Found live 2026-09-07 (wave8, pdf-pdf-cpp and pdf-graphics-in-cpp):
    TC-APT-042's cross-field frontmatter repair (segment_translator.py
    _repair_cross_field_frontmatter_residuals) calls translate_with_context
    with its own field-specific retry_feedback naming the sibling field's
    translation. When the backend passed in is a _RetryFeedbackModel (set up
    for an earlier, unrelated retry pass), the wrapper unconditionally added
    its OWN retry_feedback on top of the caller's via **kwargs, producing
    'got multiple values for keyword argument retry_feedback' -- silently
    swallowed by the repair's broad except Exception, so the repair just
    never ran (logged as 'TC-APT-042: cross-field repair call failed ...
    TypeError') and every retry pass burned ~2 minutes hitting it again.
    The caller's more specific feedback must win, not crash.
    """

    class Backend:
        def translate_with_context(self, texts, src, target, **kwargs):
            self.call = (texts, src, target, kwargs)
            return ["translated"]

    backend = Backend()
    wrapped = _RetryFeedbackModel(backend, "generic session-level retry guidance")

    result = wrapped.translate_with_context(
        ["source"],
        "en",
        "cs",
        context_hint="frontmatter_description",
        retry_feedback="specific cross-field repair feedback naming the sibling field",
    )
    assert result == ["translated"]
    assert backend.call[3]["retry_feedback"] == "specific cross-field repair feedback naming the sibling field"
    assert backend.call[3]["context_hint"] == "frontmatter_description"
