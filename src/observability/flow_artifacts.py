"""
Flow artifact generation for translation jobs.

Provides detailed per-job artifacts showing the translation flow for debugging
and audit purposes.
"""

import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from src.orchestrator.models import TranslationJob
from src.tm.models import LookupResult
from src.translation_engine.extractor.segment_extractor import Segment
from src.translation_engine.models import TranslationStats

logger = logging.getLogger(__name__)


class DetailLevel(str, Enum):
    """Detail level for flow artifacts."""

    NONE = "none"  # No artifacts
    SUMMARY = "summary"  # Job-level summary only
    SAMPLED = "sampled"  # Sample of segments (e.g., first 10)
    FULL = "full"  # All segments


class FlowArtifactWriter:
    """
    Writes per-job flow artifacts in NDJSON format.

    Each line is a JSON object representing an event in the translation flow.
    """

    def __init__(
        self,
        artifacts_dir: Path,
        detail_level: DetailLevel = DetailLevel.SUMMARY,
        sample_size: int = 10,
    ):
        """
        Initialize flow artifact writer.

        Args:
            artifacts_dir: Directory to store artifact files
            detail_level: Level of detail to capture
            sample_size: Number of segments to sample if using SAMPLED level
        """
        self.artifacts_dir = Path(artifacts_dir)
        self.detail_level = DetailLevel(detail_level)
        self.sample_size = sample_size

        # Create artifacts directory
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Track open files
        self._open_files: Dict[str, Any] = {}
        self._segment_counts: Dict[str, int] = {}

    def start_job(self, job: TranslationJob) -> None:
        """
        Initialize artifact file for a job.

        Args:
            job: Translation job starting
        """
        if self.detail_level == DetailLevel.NONE:
            return

        # Create artifact file
        artifact_path = self.artifacts_dir / f"job_{job.job_id}.ndjson"

        try:
            file_handle = open(artifact_path, "w", encoding="utf-8")
            self._open_files[job.job_id] = file_handle
            self._segment_counts[job.job_id] = 0

            # Write job start event
            event = {
                "type": "job_start",
                "timestamp": datetime.now().isoformat(),
                "job_id": job.job_id,
                "job_type": job.job_type.value,
                "site_id": job.site_id,
                "target_langs": job.target_langs,
                "input_count": len(job.input_paths),
                "priority": job.priority,
                "mode": job.mode.value,
            }
            self._write_event(job.job_id, event)

            logger.debug(f"Started flow artifact for job {job.job_id}")

        except Exception as e:
            logger.error(f"Failed to create flow artifact for job {job.job_id}: {e}")

    def record_file_start(self, job_id: str, file_path: Path, target_lang: str) -> None:
        """
        Record start of file translation.

        Args:
            job_id: Job identifier
            file_path: File being translated
            target_lang: Target language
        """
        if self.detail_level == DetailLevel.NONE:
            return

        event = {
            "type": "file_start",
            "timestamp": datetime.now().isoformat(),
            "file_path": str(file_path),
            "target_lang": target_lang,
        }
        self._write_event(job_id, event)

    def record_segment(
        self,
        job_id: str,
        segment: Segment,
        tm_result: LookupResult,
        translation: str,
        model_used: Optional[str] = None,
    ) -> None:
        """
        Record segment translation details.

        Args:
            job_id: Job identifier
            segment: Source segment
            tm_result: TM lookup result
            translation: Translated text
            model_used: Model identifier if TM miss
        """
        if self.detail_level == DetailLevel.NONE:
            return

        # Skip if using sampled mode and we've exceeded sample size
        segment_count = self._segment_counts.get(job_id, 0)
        if self.detail_level == DetailLevel.SAMPLED and segment_count >= self.sample_size:
            return

        # Increment segment count
        self._segment_counts[job_id] = segment_count + 1

        # Only record if not summary-only mode
        if self.detail_level in (DetailLevel.SAMPLED, DetailLevel.FULL):
            event = {
                "type": "segment",
                "timestamp": datetime.now().isoformat(),
                "segment_id": segment.id,
                "source_text": segment.source_text[:200],  # Truncate
                "translation": translation[:200],
                "tm_hit": tm_result.hit,
                "tm_source": tm_result.source if tm_result.hit else "none",
                "confidence": tm_result.confidence if tm_result.hit else 0.0,
                "model_used": model_used,
                "context": segment.context,
            }
            self._write_event(job_id, event)

    def record_file_complete(
        self,
        job_id: str,
        file_path: Path,
        target_lang: str,
        output_path: Path,
        segments_translated: int,
        tm_hits: int,
    ) -> None:
        """
        Record file translation completion.

        Args:
            job_id: Job identifier
            file_path: Source file
            target_lang: Target language
            output_path: Output file path
            segments_translated: Number of segments translated
            tm_hits: Number of TM hits
        """
        if self.detail_level == DetailLevel.NONE:
            return

        event = {
            "type": "file_complete",
            "timestamp": datetime.now().isoformat(),
            "file_path": str(file_path),
            "target_lang": target_lang,
            "output_path": str(output_path),
            "segments_translated": segments_translated,
            "tm_hits": tm_hits,
            "tm_hit_rate": (tm_hits / segments_translated * 100) if segments_translated > 0 else 0,
        }
        self._write_event(job_id, event)

    def finalize_job(self, job_id: str, stats: Optional[TranslationStats], success: bool) -> None:
        """
        Close artifact file and write summary.

        Args:
            job_id: Job identifier
            stats: Translation statistics
            success: Whether job succeeded
        """
        if self.detail_level == DetailLevel.NONE:
            return

        # Write job completion event
        event = {
            "type": "job_complete",
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "stats": (
                {
                    "total_segments": stats.total_segments,
                    "tm_hits": stats.tm_hits,
                    "translated_segments": stats.translated_segments,
                    "duration_seconds": stats.duration_seconds,
                    "words_translated": stats.words_translated,
                    "tm_hit_rate": (
                        (stats.tm_hits / stats.total_segments * 100) if stats.total_segments > 0 else 0
                    ),
                }
                if stats
                else None
            ),
        }
        self._write_event(job_id, event)

        # Close file
        if job_id in self._open_files:
            try:
                self._open_files[job_id].close()
                del self._open_files[job_id]
                del self._segment_counts[job_id]
                logger.debug(f"Finalized flow artifact for job {job_id}")
            except Exception as e:
                logger.error(f"Failed to finalize flow artifact for job {job_id}: {e}")

    def _write_event(self, job_id: str, event: Dict[str, Any]) -> None:
        """
        Write event to artifact file.

        Args:
            job_id: Job identifier
            event: Event dictionary
        """
        if job_id not in self._open_files:
            logger.warning(f"No open artifact file for job {job_id}")
            return

        try:
            file_handle = self._open_files[job_id]
            json_line = json.dumps(event, ensure_ascii=False)
            file_handle.write(json_line + "\n")
            file_handle.flush()
        except Exception as e:
            logger.error(f"Failed to write event to artifact for job {job_id}: {e}")

    def close_all(self) -> None:
        """Close all open artifact files."""
        for job_id, file_handle in list(self._open_files.items()):
            try:
                file_handle.close()
                logger.debug(f"Closed artifact file for job {job_id}")
            except Exception as e:
                logger.error(f"Failed to close artifact file for job {job_id}: {e}")

        self._open_files.clear()
        self._segment_counts.clear()


def read_flow_artifact(artifact_path: Path) -> list[Dict[str, Any]]:
    """
    Read and parse a flow artifact file.

    Args:
        artifact_path: Path to artifact file

    Returns:
        List of event dictionaries
    """
    events = []

    try:
        with open(artifact_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    event = json.loads(line)
                    events.append(event)
    except Exception as e:
        logger.error(f"Failed to read flow artifact {artifact_path}: {e}")

    return events


def get_job_summary(artifact_path: Path) -> Optional[Dict[str, Any]]:
    """
    Extract job summary from flow artifact.

    Args:
        artifact_path: Path to artifact file

    Returns:
        Job summary dictionary or None if not found
    """
    events = read_flow_artifact(artifact_path)

    if not events:
        return None

    # Find job_start and job_complete events
    job_start = None
    job_complete = None

    for event in events:
        if event.get("type") == "job_start":
            job_start = event
        elif event.get("type") == "job_complete":
            job_complete = event

    if not job_start or not job_complete:
        return None

    # Build summary
    summary = {
        "job_id": job_start.get("job_id"),
        "job_type": job_start.get("job_type"),
        "site_id": job_start.get("site_id"),
        "target_langs": job_start.get("target_langs"),
        "input_count": job_start.get("input_count"),
        "success": job_complete.get("success"),
        "stats": job_complete.get("stats"),
        "start_time": job_start.get("timestamp"),
        "end_time": job_complete.get("timestamp"),
    }

    return summary
