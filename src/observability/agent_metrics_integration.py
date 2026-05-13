"""Integration helper for wiring Agent Metrics into workers.

Keeps worker code changes minimal — one call before content_root,
one call after.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_agent_metrics_config(config_service) -> dict:
    """Load agent_metrics config from global.yaml. Returns {} if missing."""
    try:
        raw = config_service.get_config() if config_service else {}
        return raw.get("agent_metrics", {})
    except Exception:
        return {}


def _is_excluded(site_id: str, cfg: dict) -> bool:
    prefixes = cfg.get("excluded_site_id_prefixes", [])
    return any(site_id.startswith(p) for p in prefixes)


def _build_item_name(resolved, job_type: str, items_succeeded: int) -> str:
    """Build human-readable item_name: verb + family + section + file count."""
    verb_map = {
        "Content Translation": "Translated",
        "TM Improvement": "Improved TM for",
        "Test": "Tested",
    }
    verb = verb_map.get(job_type, job_type)
    family_token = getattr(resolved, "product_family_token", "total") or "total"
    family = "All Products" if family_token == "total" else family_token.capitalize()
    section = getattr(resolved, "website_section", "") or "Content"
    noun = "file" if items_succeeded == 1 else "files"
    return f"{verb} {family} {section} — {items_succeeded} {noun}"


class MetricsRunContext:
    """Wraps a single content_root translation run for metrics collection."""

    def __init__(
        self,
        site_id: str,
        content_root_raw: str,
        config_service,
        job_type: str = "content_translation",
        profile_filename: str = "",
        display_name: str | None = None,
    ):
        self.site_id = site_id
        self.content_root_raw = content_root_raw
        self.job_type = job_type
        self.profile_filename = profile_filename
        self.display_name = display_name
        self.config_service = config_service

        self._cfg = _load_agent_metrics_config(config_service)
        self._enabled = self._cfg.get("enabled", False)
        self._dry_run = self._cfg.get("dry_run", True)
        self._start_time: float | None = None
        self._parent_run_id = str(uuid.uuid4())
        self._llm_ctx = None

    @property
    def enabled(self) -> bool:
        return self._enabled and not _is_excluded(self.site_id, self._cfg)

    def start(self) -> None:
        """Call before translation begins."""
        if not self.enabled:
            return
        self._start_time = time.time()
        try:
            from src.observability.llm_run_context import LLMRunContext
            self._llm_ctx = LLMRunContext.start_run()
        except Exception as e:
            logger.debug("LLMRunContext start failed: %s", e)

    def abort(self, error_detail: str = "Worker aborted before content_root completed") -> dict | None:
        """Call if content_root fails or is killed before finish().

        Writes a failure sidecar (dry_run only — no HTTP POST) with whatever LLM
        counters have accumulated so far. Item counts are set to 0/unknown at abort time.
        Safe to call at any point after start(); no-op when not enabled.
        """
        if not self.enabled:
            return None
        logger.debug("Agent metrics abort: %s", error_detail[:120])
        return self.finish(
            items_discovered=0,
            items_succeeded=0,
            items_failed=0,
            error_detail=error_detail,
        )

    def finish(
        self,
        items_discovered: int,
        items_succeeded: int,
        items_failed: int,
        error_detail: str | None = None,
    ) -> dict | None:
        """Call after translation completes. Returns post result or None."""
        if not self.enabled:
            return None

        run_duration_ms = int((time.time() - (self._start_time or time.time())) * 1000)

        # Checkpoint LLM counters
        token_usage = 0
        api_calls_count = 0
        call_accounting = {}
        if self._llm_ctx:
            try:
                from src.observability.llm_run_context import LLMRunContext
                delta = self._llm_ctx.checkpoint()
                token_usage = delta.token_usage
                api_calls_count = delta.api_calls_count
                call_accounting = {
                    "attempted_provider_calls": delta.attempted_provider_calls,
                    "completed_provider_calls": delta.completed_provider_calls,
                    "failed_provider_calls": delta.failed_provider_calls,
                    "total_input_tokens": delta.total_input_tokens,
                    "total_output_tokens": delta.total_output_tokens,
                    "token_usage_posted": token_usage,
                    "api_calls_count_posted": api_calls_count,
                }
                LLMRunContext.end_run()
            except Exception as e:
                logger.debug("LLMRunContext checkpoint failed: %s", e)

        try:
            return self._build_and_post(
                items_discovered=items_discovered,
                items_succeeded=items_succeeded,
                items_failed=items_failed,
                run_duration_ms=run_duration_ms,
                token_usage=token_usage,
                api_calls_count=api_calls_count,
                call_accounting=call_accounting,
                error_detail=error_detail,
            )
        except Exception as e:
            logger.warning("Agent metrics posting failed: %s", e)
            return None

    def _build_and_post(
        self,
        items_discovered: int,
        items_succeeded: int,
        items_failed: int,
        run_duration_ms: int,
        token_usage: int,
        api_calls_count: int,
        call_accounting: dict,
        error_detail: str | None,
    ) -> dict:
        from src.observability.metrics_scope import (
            ScopeResolver,
            ScopeInput,
            derive_content_root_id,
            generate_stable_work_slice_id,
            generate_execution_attempt_id,
            generate_segment_run_id,
        )
        from src.observability.agent_metrics_payload import (
            AgentMetricsPayload,
            determine_status,
            make_timestamp,
        )
        from src.observability.gitlab_context import collect_gitlab_context
        from src.observability.metrics_evidence import EvidenceWriter
        from src.observability.agent_metrics_poster import AgentMetricsPoster

        # Resolve scope
        content_root_id = derive_content_root_id(self.content_root_raw)
        resolver = ScopeResolver(config=self._cfg)
        scope_input = ScopeInput(
            site_id=self.site_id,
            content_root_raw=self.content_root_raw,
            profile_filename=self.profile_filename,
            display_name=self.display_name,
        )
        resolved = resolver.resolve(scope_input)

        # Generate IDs
        gitlab_ctx = collect_gitlab_context()
        ws_id = generate_stable_work_slice_id(
            site_id=self.site_id,
            content_root_id=content_root_id,
            product_family_token=resolved.product_family_token,
            platform=resolved.platform,
            operation_type=self.job_type,
        )
        ea_id = generate_execution_attempt_id(
            parent_run_id=self._parent_run_id,
            gitlab_ctx=gitlab_ctx,
        )
        seg_id = generate_segment_run_id(ws_id, ea_id)

        # Build payload
        status = determine_status(items_succeeded, items_failed, items_discovered)
        payload = AgentMetricsPayload(
            timestamp=make_timestamp(),
            job_type=self.job_type,
            run_id=str(seg_id),
            status=status,
            product=resolved.product,
            platform=resolved.platform,
            website=resolved.website,
            website_section=resolved.website_section,
            item_name=_build_item_name(resolved, self.job_type, items_succeeded),
            items_discovered=items_discovered,
            items_failed=items_failed,
            items_succeeded=items_succeeded,
            run_duration_ms=run_duration_ms,
            token_usage=token_usage,
            api_calls_count=api_calls_count,
        )
        post_dict = payload.to_post_dict()

        # Detect LLM provider info
        llm_provider = self._detect_llm_provider()

        # Evidence lifecycle
        evidence_dir = self._cfg.get("evidence_dir", "data/metrics/agent_evidence")
        ledger_file = self._cfg.get("ledger_file")
        ew = EvidenceWriter(evidence_dir=evidence_dir, ledger_file=ledger_file)

        ids = {
            "stable_work_slice_id": str(ws_id),
            "execution_attempt_id": str(ea_id),
            "segment_run_id": str(seg_id),
            "parent_run_id": self._parent_run_id,
        }
        scope_dict = {
            "site_id": resolved.site_id,  # normalized canonical value (e.g. "docs.aspose.net")
            "source_site_domain": resolved.source_site_domain,
            "content_root_raw": self.content_root_raw,
            "content_root_id": resolved.content_root_id,
            "website": resolved.website,
            "website_section": resolved.website_section,
            "product": resolved.product,
            "product_family_token": resolved.product_family_token,
            "platform": resolved.platform,
            "locale_grain": "all",
            "operation_type": self.job_type,
            "detection_method": resolved.detection_method,
            "fallback_used": resolved.fallback_used,
            "reporting_confidence": resolved.reporting_confidence,
            "warnings": resolved.warnings,
        }
        exec_ctx = gitlab_ctx.to_dict()
        items_detail = {
            "total_files_selected": items_discovered,
            "total_files_succeeded": items_succeeded,
            "total_files_failed": items_failed,
        }

        lifecycle = ew.full_post_lifecycle(
            segment_run_id=str(seg_id),
            ids=ids,
            execution_context=exec_ctx,
            scope=scope_dict,
            llm_provider=llm_provider,
            posted_payload=post_dict,
            call_accounting=call_accounting,
            items_detail=items_detail,
            error_detail=error_detail,
            trigger_type="ci" if gitlab_ctx.is_ci else "scheduled",
            output_summary=f"{items_succeeded}/{items_discovered} files for {self.site_id}",
            dry_run=self._dry_run,
        )

        if lifecycle["action"] == "skipped_duplicate":
            logger.info("Metrics: duplicate segment_run_id %s, skipping", seg_id)
            return lifecycle

        if lifecycle["action"] == "dry_run":
            logger.info("Metrics DRY RUN: payload logged for %s (%s)", self.site_id, content_root_id)
            return lifecycle

        # Actually post
        poster = AgentMetricsPoster(
            endpoint_env=self._cfg.get("endpoint_env", "AGENT_METRICS_ENDPOINT"),
            token_env=self._cfg.get("token_env", "AGENT_METRICS_TOKEN"),
            timeout_seconds=self._cfg.get("post_timeout_seconds", 15),
            dry_run=False,
            fire_and_forget=self._cfg.get("fire_and_forget", False),
        )
        result = poster.post(post_dict, job_type=self.job_type)

        if result["posted"]:
            ew.record_post_success(str(seg_id), result.get("response_code") or 0)
        else:
            ew.record_post_failure(str(seg_id), result.get("error", "unknown"))

        return result

    def _detect_llm_provider(self) -> dict:
        """Detect which LLM provider was used."""
        try:
            raw = self.config_service.get_config() if self.config_service else {}
            model_id = raw.get("llm_escalation_model", "professionalize_llm")
            # Try to read model registry
            from src.model_runtime.registry import ModelRegistry
            reg = ModelRegistry()
            info = reg.get_model(model_id)
            provider_name = getattr(info, "provider", "unknown")
            endpoint = getattr(info, "base_url", "") or ""
            model_name = getattr(info, "model_name", "") or getattr(info, "model", "") or ""
            endpoint_host = ""
            if endpoint:
                from urllib.parse import urlparse
                endpoint_host = urlparse(endpoint).hostname or ""
            is_prof = "professionalize.com" in endpoint_host
            return {
                "provider_name": provider_name,
                "model_name": model_name,
                "endpoint_host": endpoint_host,
                "is_professionalize": is_prof,
            }
        except Exception:
            return {
                "provider_name": "unknown",
                "model_name": "unknown",
                "endpoint_host": "unknown",
                "is_professionalize": False,
            }
