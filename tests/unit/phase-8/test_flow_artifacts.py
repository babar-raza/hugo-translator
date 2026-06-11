"""
Unit tests for flow artifact generation.
"""

import tempfile
from pathlib import Path

import pytest

from src.observability.flow_artifacts import (
    DetailLevel,
    FlowArtifactWriter,
    get_job_summary,
    read_flow_artifact,
)
from src.orchestrator.models import JobMode, JobType, TranslationJob
from src.tm.models import LookupResult
from src.translation_engine.extractor.segment_extractor import Segment
from src.translation_engine.models import TranslationStats


@pytest.fixture
def temp_artifacts_dir():
    """Create temporary artifacts directory."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_job():
    """Create sample translation job."""
    return TranslationJob(
        job_id="test_job_001",
        job_type=JobType.FILE,
        site_id="test.site",
        target_langs=["fr", "es"],
        input_paths=[Path("/test/file.md")],
        priority=5,
        mode=JobMode.MANUAL,
    )


@pytest.fixture
def sample_segment():
    """Create sample segment."""
    return Segment(
        id="seg_001",
        source_text="Hello world",
        context={"type": "body", "path": "paragraph"},
        site_id="test.site",
        source_lang="en",
        placeholder_map={},
        metadata={},
    )


@pytest.fixture
def sample_stats():
    """Create sample translation stats."""
    return TranslationStats(
        total_segments=10,
        tm_hits=7,
        translated_segments=3,
        duration_seconds=1.5,
        words_translated=50,
    )


class TestFlowArtifactWriter:
    """Test FlowArtifactWriter."""

    def test_writer_initialization(self, temp_artifacts_dir):
        """Test writer initialization."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.FULL)

        assert writer.artifacts_dir == temp_artifacts_dir
        assert writer.detail_level == DetailLevel.FULL
        assert temp_artifacts_dir.exists()

    def test_start_job_creates_file(self, temp_artifacts_dir, sample_job):
        """Test that start_job creates artifact file."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.FULL)
        writer.start_job(sample_job)

        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        assert artifact_file.exists()

        # Check first event
        events = read_flow_artifact(artifact_file)
        assert len(events) >= 1
        assert events[0]["type"] == "job_start"
        assert events[0]["job_id"] == sample_job.job_id

    def test_start_job_none_level(self, temp_artifacts_dir, sample_job):
        """Test that NONE level creates no artifacts."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.NONE)
        writer.start_job(sample_job)

        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        assert not artifact_file.exists()

    def test_record_segment_full_level(self, temp_artifacts_dir, sample_job, sample_segment):
        """Test recording segments with FULL detail level."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.FULL)
        writer.start_job(sample_job)

        tm_result = LookupResult(
            hit=True,
            translation="Bonjour le monde",
            source="l2_exact",
            confidence=1.0,
            candidates=[],
            metadata={},
        )

        writer.record_segment(
            sample_job.job_id, sample_segment, tm_result, translation="Bonjour le monde"
        )

        # Check segment event was written
        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        events = read_flow_artifact(artifact_file)

        segment_events = [e for e in events if e["type"] == "segment"]
        assert len(segment_events) == 1
        assert segment_events[0]["segment_id"] == sample_segment.id
        assert segment_events[0]["tm_hit"] is True
        assert segment_events[0]["tm_source"] == "l2_exact"

    def test_record_segment_summary_level(self, temp_artifacts_dir, sample_job, sample_segment):
        """Test that SUMMARY level doesn't record segments."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.SUMMARY)
        writer.start_job(sample_job)

        tm_result = LookupResult(
            hit=False, translation=None, source="none", confidence=0.0, candidates=[], metadata={}
        )

        writer.record_segment(
            sample_job.job_id, sample_segment, tm_result, translation="Bonjour", model_used="m2m100"
        )

        # Check no segment events
        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        events = read_flow_artifact(artifact_file)

        segment_events = [e for e in events if e["type"] == "segment"]
        assert len(segment_events) == 0

    def test_record_segment_sampled_level(self, temp_artifacts_dir, sample_job, sample_segment):
        """Test SAMPLED level respects sample size."""
        writer = FlowArtifactWriter(
            temp_artifacts_dir, detail_level=DetailLevel.SAMPLED, sample_size=3
        )
        writer.start_job(sample_job)

        tm_result = LookupResult(
            hit=False, translation=None, source="none", confidence=0.0, candidates=[], metadata={}
        )

        # Record 5 segments
        for i in range(5):
            segment = Segment(
                id=f"seg_{i:03d}",
                source_text=f"Text {i}",
                context={"type": "body"},
                site_id="test.site",
                source_lang="en",
                placeholder_map={},
                metadata={},
            )
            writer.record_segment(sample_job.job_id, segment, tm_result, translation=f"Texte {i}")

        # Check only 3 segments recorded
        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        events = read_flow_artifact(artifact_file)

        segment_events = [e for e in events if e["type"] == "segment"]
        assert len(segment_events) == 3

    def test_record_file_start(self, temp_artifacts_dir, sample_job):
        """Test recording file start."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.FULL)
        writer.start_job(sample_job)

        writer.record_file_start(sample_job.job_id, Path("/test/file.md"), "fr")

        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        events = read_flow_artifact(artifact_file)

        file_start_events = [e for e in events if e["type"] == "file_start"]
        assert len(file_start_events) == 1
        assert file_start_events[0]["target_lang"] == "fr"

    def test_record_file_complete(self, temp_artifacts_dir, sample_job):
        """Test recording file completion."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.FULL)
        writer.start_job(sample_job)

        writer.record_file_complete(
            sample_job.job_id,
            Path("/test/file.md"),
            "fr",
            Path("/test/fr/file.md"),
            segments_translated=10,
            tm_hits=7,
        )

        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        events = read_flow_artifact(artifact_file)

        file_complete_events = [e for e in events if e["type"] == "file_complete"]
        assert len(file_complete_events) == 1
        assert file_complete_events[0]["segments_translated"] == 10
        assert file_complete_events[0]["tm_hits"] == 7
        assert file_complete_events[0]["tm_hit_rate"] == 70.0

    def test_finalize_job(self, temp_artifacts_dir, sample_job, sample_stats):
        """Test finalizing job."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.FULL)
        writer.start_job(sample_job)
        writer.finalize_job(sample_job.job_id, sample_stats, success=True)

        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        events = read_flow_artifact(artifact_file)

        # Check job_complete event
        complete_events = [e for e in events if e["type"] == "job_complete"]
        assert len(complete_events) == 1
        assert complete_events[0]["success"] is True
        assert complete_events[0]["stats"]["total_segments"] == 10
        assert complete_events[0]["stats"]["tm_hits"] == 7

        # Check file is closed
        assert sample_job.job_id not in writer._open_files

    def test_close_all(self, temp_artifacts_dir, sample_job):
        """Test closing all open files."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.FULL)

        # Start multiple jobs
        jobs = []
        for i in range(3):
            job = TranslationJob(
                job_id=f"test_job_{i:03d}",
                job_type=JobType.FILE,
                site_id="test.site",
                target_langs=["fr"],
                input_paths=[Path(f"/test/file_{i}.md")],
                priority=5,
                mode=JobMode.MANUAL,
            )
            jobs.append(job)
            writer.start_job(job)

        assert len(writer._open_files) == 3

        writer.close_all()

        assert len(writer._open_files) == 0
        assert len(writer._segment_counts) == 0

    def test_long_text_truncation(self, temp_artifacts_dir, sample_job):
        """Test that long text is truncated."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.FULL)
        writer.start_job(sample_job)

        long_text = "x" * 300
        segment = Segment(
            id="seg_001",
            source_text=long_text,
            context={"type": "body"},
            site_id="test.site",
            source_lang="en",
            placeholder_map={},
            metadata={},
        )

        tm_result = LookupResult(
            hit=False, translation=None, source="none", confidence=0.0, candidates=[], metadata={}
        )

        writer.record_segment(sample_job.job_id, segment, tm_result, translation=long_text)

        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        events = read_flow_artifact(artifact_file)

        segment_events = [e for e in events if e["type"] == "segment"]
        assert len(segment_events[0]["source_text"]) <= 200
        assert len(segment_events[0]["translation"]) <= 200


class TestFlowArtifactReading:
    """Test flow artifact reading functions."""

    def test_read_flow_artifact(self, temp_artifacts_dir, sample_job):
        """Test reading flow artifact."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.FULL)
        writer.start_job(sample_job)
        writer.finalize_job(sample_job.job_id, None, success=True)

        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        events = read_flow_artifact(artifact_file)

        assert len(events) >= 2
        assert events[0]["type"] == "job_start"
        assert events[-1]["type"] == "job_complete"

    def test_read_nonexistent_artifact(self, temp_artifacts_dir):
        """Test reading nonexistent artifact."""
        events = read_flow_artifact(temp_artifacts_dir / "nonexistent.ndjson")
        assert events == []

    def test_get_job_summary(self, temp_artifacts_dir, sample_job, sample_stats):
        """Test extracting job summary."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.FULL)
        writer.start_job(sample_job)
        writer.finalize_job(sample_job.job_id, sample_stats, success=True)

        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        summary = get_job_summary(artifact_file)

        assert summary is not None
        assert summary["job_id"] == sample_job.job_id
        assert summary["site_id"] == sample_job.site_id
        assert summary["success"] is True
        assert summary["stats"]["total_segments"] == 10
        assert summary["stats"]["tm_hits"] == 7

    def test_get_job_summary_incomplete(self, temp_artifacts_dir, sample_job):
        """Test summary with incomplete artifact."""
        writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=DetailLevel.FULL)
        writer.start_job(sample_job)
        # Don't finalize - incomplete artifact

        artifact_file = temp_artifacts_dir / f"job_{sample_job.job_id}.ndjson"
        summary = get_job_summary(artifact_file)

        # Should return None for incomplete artifact
        assert summary is None

    def test_get_job_summary_nonexistent(self, temp_artifacts_dir):
        """Test summary for nonexistent artifact."""
        summary = get_job_summary(temp_artifacts_dir / "nonexistent.ndjson")
        assert summary is None


class TestDetailLevels:
    """Test different detail levels."""

    def test_detail_level_enum(self):
        """Test detail level enum values."""
        assert DetailLevel.NONE == "none"
        assert DetailLevel.SUMMARY == "summary"
        assert DetailLevel.SAMPLED == "sampled"
        assert DetailLevel.FULL == "full"

    def test_all_detail_levels_work(self, temp_artifacts_dir, sample_job, sample_segment):
        """Test that all detail levels work without errors."""
        tm_result = LookupResult(
            hit=False, translation=None, source="none", confidence=0.0, candidates=[], metadata={}
        )

        for level in [DetailLevel.NONE, DetailLevel.SUMMARY, DetailLevel.SAMPLED, DetailLevel.FULL]:
            writer = FlowArtifactWriter(temp_artifacts_dir, detail_level=level)
            writer.start_job(sample_job)
            writer.record_segment(sample_job.job_id, sample_segment, tm_result, translation="Test")
            writer.finalize_job(sample_job.job_id, None, success=True)
