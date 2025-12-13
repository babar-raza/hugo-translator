"""
Data models for orchestrator jobs and states.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class JobType(str, Enum):
    """Types of translation jobs."""

    FILE = "file"  # Single file translation
    DIRECTORY = "directory"  # Directory batch translation
    SWEEP_BATCH = "sweep_batch"  # Batch from sweep operation


class JobStatus(str, Enum):
    """Job execution states."""

    PENDING = "pending"  # In queue, not yet started
    RUNNING = "running"  # Currently being processed
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"  # Error occurred
    CANCELLED = "cancelled"  # User cancelled


class JobMode(str, Enum):
    """Job trigger modes."""

    AUTO = "auto"  # Triggered automatically (file watcher, sweep)
    MANUAL = "manual"  # User-initiated


@dataclass
class TranslationJob:
    """A unit of work for translation."""

    job_id: str
    job_type: JobType
    site_id: str
    target_langs: List[str]
    input_paths: List[Path]
    priority: int = 5  # Lower = higher priority (1-10)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: JobStatus = JobStatus.PENDING
    mode: JobMode = JobMode.MANUAL
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    result_summary: Optional[Dict[str, Any]] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate job duration if started."""
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds()

    def __lt__(self, other: "TranslationJob") -> bool:
        """Compare jobs for priority queue (lower priority value = higher priority)."""
        if self.priority != other.priority:
            return self.priority < other.priority
        # If same priority, FIFO (older jobs first)
        return self.created_at < other.created_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for serialization."""
        return {
            "job_id": self.job_id,
            "job_type": self.job_type.value,
            "site_id": self.site_id,
            "target_langs": self.target_langs,
            "input_paths": [str(p) for p in self.input_paths],
            "priority": self.priority,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status.value,
            "mode": self.mode.value,
            "metadata": self.metadata,
            "error_message": self.error_message,
            "result_summary": self.result_summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranslationJob":
        """Create job from dictionary."""
        return cls(
            job_id=data["job_id"],
            job_type=JobType(data["job_type"]),
            site_id=data["site_id"],
            target_langs=data["target_langs"],
            input_paths=[Path(p) for p in data["input_paths"]],
            priority=data.get("priority", 5),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            status=JobStatus(data.get("status", "pending")),
            mode=JobMode(data.get("mode", "manual")),
            metadata=data.get("metadata", {}),
            error_message=data.get("error_message"),
            result_summary=data.get("result_summary"),
        )


@dataclass
class JobStats:
    """Statistics for job queue."""

    total_enqueued: int = 0
    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0

    # Legacy aliases for backward compatibility
    @property
    def total_jobs(self) -> int:
        """Total jobs enqueued."""
        return self.total_enqueued

    @property
    def pending_jobs(self) -> int:
        """Pending jobs."""
        return self.pending

    @property
    def running_jobs(self) -> int:
        """Running jobs."""
        return self.running

    @property
    def completed_jobs(self) -> int:
        """Completed jobs."""
        return self.completed

    @property
    def failed_jobs(self) -> int:
        """Failed jobs."""
        return self.failed

    @property
    def active_jobs(self) -> int:
        """Total of pending and running jobs."""
        return self.pending + self.running
