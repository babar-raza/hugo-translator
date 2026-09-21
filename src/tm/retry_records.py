"""Versioned, payload-safe contracts for TM intents and retry tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Mapping

SCHEMA_VERSION = 1
_TERMINAL = frozenset({"ACCEPTED", "DEAD_LETTER"})


def _text(value: Any, name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _sha256(value: Any, name: str) -> str:
    value = _text(value, name).lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a sha256 hex digest")
    return value


@dataclass(frozen=True)
class TMWriteIntentRecord:
    site_id: str
    src_lang: str
    tgt_lang: str
    text: str
    translation: str
    context: str | None = None
    field_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, record: Mapping[str, Any]) -> TMWriteIntentRecord:
        version = int(record.get("schema_version", SCHEMA_VERSION))
        if version > SCHEMA_VERSION:
            raise ValueError(f"unsupported future TM intent schema_version={version}")
        return cls(
            site_id=_text(record.get("site_id"), "site_id"),
            src_lang=_text(record.get("src_lang"), "src_lang"),
            tgt_lang=_text(record.get("tgt_lang"), "tgt_lang"),
            text=_text(record.get("text"), "text"),
            translation=_text(record.get("translation"), "translation"),
            context=record.get("context"),
            field_name=str(record.get("field_name") or ""),
            metadata=dict(record.get("metadata") or {}),
            schema_version=version,
        )

    def intent_id(self) -> str:
        stable = "\x1f".join(
            (
                self.site_id,
                self.src_lang,
                self.tgt_lang,
                self.text,
                self.translation,
                self.context or "",
                self.field_name,
            )
        )
        return sha256(stable.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RejectedTranslationTask:
    campaign_id: str
    site_id: str
    source_path: str
    output_path: str
    source_sha256: str
    target_lang: str
    failure_category: str
    failure_fingerprint: str
    retry_budget: int
    model_target: str
    state: str = "QUEUED"
    terminal_receipt_id: str | None = None
    terminal_ticket_id: str | None = None
    schema_version: int = SCHEMA_VERSION
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, record: Mapping[str, Any]) -> RejectedTranslationTask:
        version = int(record.get("schema_version", SCHEMA_VERSION))
        if version > SCHEMA_VERSION:
            raise ValueError(f"unsupported future retry task schema_version={version}")
        state = _text(record.get("state", "QUEUED"), "state").upper()
        receipt = record.get("terminal_receipt_id")
        ticket = record.get("terminal_ticket_id")
        if state in _TERMINAL and not (receipt or ticket):
            raise ValueError(
                "terminal retry task requires terminal_receipt_id or terminal_ticket_id"
            )
        if int(record.get("retry_budget", 0)) < 0:
            raise ValueError("retry_budget must be >= 0")
        known = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(
            campaign_id=_text(record.get("campaign_id"), "campaign_id"),
            site_id=_text(record.get("site_id"), "site_id"),
            source_path=_text(record.get("source_path"), "source_path"),
            output_path=_text(record.get("output_path"), "output_path"),
            source_sha256=_sha256(record.get("source_sha256"), "source_sha256"),
            target_lang=_text(record.get("target_lang"), "target_lang"),
            failure_category=_text(record.get("failure_category"), "failure_category"),
            failure_fingerprint=_text(record.get("failure_fingerprint"), "failure_fingerprint"),
            retry_budget=int(record.get("retry_budget", 0)),
            model_target=_text(record.get("model_target"), "model_target"),
            state=state,
            terminal_receipt_id=str(receipt) if receipt else None,
            terminal_ticket_id=str(ticket) if ticket else None,
            schema_version=version,
            extensions={key: value for key, value in record.items() if key not in known},
        )


def adapt_legacy_record(kind: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve every legacy field; return a canonical task only when safe."""
    raw = dict(record)
    if kind == "heal":
        candidate = {
            "campaign_id": raw.get("campaign_id"),
            "site_id": raw.get("site_id"),
            "source_path": raw.get("source_path"),
            "output_path": raw.get("output_path"),
            "source_sha256": raw.get("source_sha256"),
            "target_lang": raw.get("target_lang"),
            "failure_category": raw.get("root_cause_class", "legacy_heal"),
            "failure_fingerprint": raw.get("ticket_id", "legacy_heal"),
            "retry_budget": raw.get("retry_budget", 0),
            "model_target": raw.get("processing_model") or "professionalize_llm",
        }
    elif kind == "retranslate":
        candidate = {
            "campaign_id": raw.get("campaign_id", "legacy-retranslate"),
            "site_id": raw.get("site_id", "unknown"),
            "source_path": raw.get("source_path"),
            "output_path": raw.get("output_path"),
            "source_sha256": raw.get("source_sha256"),
            "target_lang": raw.get("tgt_lang"),
            "failure_category": "legacy_retranslate",
            "failure_fingerprint": raw.get("output_path", "legacy_retranslate"),
            "retry_budget": raw.get("retry_count", 0),
            "model_target": "professionalize_llm",
        }
    elif kind == "improvement":
        candidate = {
            "campaign_id": raw.get("campaign_id", "legacy-improvement"),
            "site_id": raw.get("site_id"),
            "source_path": raw.get("source_path"),
            "output_path": raw.get("output_path"),
            "source_sha256": raw.get("source_sha256"),
            "target_lang": raw.get("tgt_lang"),
            "failure_category": "legacy_improvement",
            "failure_fingerprint": raw.get("candidate_id", "legacy_improvement"),
            "retry_budget": raw.get("retry_count", 0),
            "model_target": "professionalize_llm",
        }
    else:
        raise ValueError(f"unknown legacy record kind: {kind}")
    try:
        task = RejectedTranslationTask.from_mapping(candidate)
    except ValueError as exc:
        return {
            "disposition": "UNRESOLVED_LEGACY",
            "reason": str(exc),
            "legacy_kind": kind,
            "raw": raw,
        }
    return {"disposition": "ADAPTED", "legacy_kind": kind, "task": task, "raw": raw}
