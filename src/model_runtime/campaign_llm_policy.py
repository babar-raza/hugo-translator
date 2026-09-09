"""Call-scoped campaign policy and payload-free provider accounting."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from uuid import uuid4

_policy = ContextVar("campaign_llm_policy", default=None)
_category = ContextVar("campaign_llm_category", default=None)


class DeferredLLMCall(RuntimeError):
    """The candidate must reach the durable retry queue instead of a provider."""


@contextmanager
def campaign_llm_scope(mode, category, sink, **identity):
    if mode not in {"immediate", "deferred"}:
        raise ValueError(f"invalid LLM retry mode: {mode}")
    token = _policy.set({"mode": mode, "category": category, "sink": sink, **identity})
    try:
        yield
    finally:
        _policy.reset(token)


def llm_category(category):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            token = _category.set(category)
            try:
                return function(*args, **kwargs)
            finally:
                _category.reset(token)

        return wrapped

    return decorate


def accounted_generate(model_id, generate):
    policy = _policy.get()
    if policy is None:
        return generate()
    category = _category.get() or policy["category"]
    event = {
        "schema_version": 1,
        "call_id": uuid4().hex,
        "model_id": model_id,
        "category": category,
        **{key: value for key, value in policy.items() if key not in {"sink", "category"}},
    }
    sink = policy["sink"]
    if policy["mode"] == "deferred" and category != "validation":
        sink({**event, "outcome": "deferred"})
        raise DeferredLLMCall(f"{category} queued by deferred campaign policy")
    sink({**event, "outcome": "started"})
    try:
        result = generate()
    except BaseException as exc:
        sink({**event, "outcome": "failed", "error_class": type(exc).__name__})
        raise
    sink({**event, "outcome": "completed", "input_tokens": result[1], "output_tokens": result[2]})
    return result
