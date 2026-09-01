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
