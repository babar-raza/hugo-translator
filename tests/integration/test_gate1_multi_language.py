"""Gate 1 integration test - Multi-language translation."""
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROFILES_DIR = Path(__file__).parent.parent.parent / "config" / "site_profiles"
_EXAMPLE_AVAILABLE = (_PROFILES_DIR / "test.example.net.yaml").exists()
_SCALE_AVAILABLE = (_PROFILES_DIR / "test.scale.net.yaml").exists()
_INTERRUPT_AVAILABLE = (_PROFILES_DIR / "test.interrupt.net.yaml").exists()


@pytest.mark.skipif(not _EXAMPLE_AVAILABLE, reason="Site profile test.example.net.yaml not present")
def test_multi_language_no_cascading_timeout(tmp_path):
    """Test multi-language translation completes without cascading timeouts."""
    # Minimal test corpus
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "test.md").write_text("# Test\n\nHello world.\n")

    output_dir = tmp_path / "output"

    # Run translation with 3 languages
    start = time.time()
    result = subprocess.run(
        [
            sys.executable, "-m", "src.cli",
            "--site", "test.example.net",
            "--input", str(source_dir),
            "--output", str(output_dir),
            "--target-langs", "ar,bg,cs",
        ],
        capture_output=True,
        text=True,
        timeout=120,  # 2 minutes max (vs 15+ minutes with bug)
    )
    duration = time.time() - start

    # Verify success
    assert result.returncode == 0, f"Translation failed: {result.stderr}"

    # Verify performance (should be <60s, not 15+ minutes)
    assert duration < 60, f"Translation took {duration}s (expected <60s)"

    # Verify all languages produced output
    for lang in ["ar", "bg", "cs"]:
        lang_dir = output_dir / "test.example.net" / lang
        assert lang_dir.exists(), f"Output for {lang} not found"
        assert (lang_dir / "test.md").exists(), f"Translated file for {lang} not found"

    # Verify logs contain parent lock pattern
    assert "Site lock acquired by parent process" in result.stdout or "Site lock acquired by parent process" in result.stderr, \
        "Parent lock acquisition not logged"

    # Count child skip messages (should be 3 for 3 languages)
    skip_count = (result.stdout + result.stderr).count("Skipping site lock acquisition")
    assert skip_count >= 3, f"Expected 3+ skip messages, got {skip_count}"

    # Verify NO cascading timeouts
    assert "Still waiting for lock" not in result.stdout, \
        "Found 'Still waiting for lock' message (cascading timeout detected)"
    assert "300s elapsed" not in result.stdout, \
        "Found '300s elapsed' message (5-minute timeout detected)"


@pytest.mark.skipif(not _INTERRUPT_AVAILABLE, reason="Site profile test.interrupt.net.yaml not present")
def test_parent_lock_cleanup_on_interrupt(tmp_path):
    """Test parent lock is cleaned up on Ctrl+C."""
    import signal

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "test.md").write_text("# Test\n\nHello world.\n")

    output_dir = tmp_path / "output"

    # Start translation process
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "src.cli",
            "--site", "test.interrupt.net",
            "--source", str(source_dir),
            "--output", str(output_dir),
            "--target-langs", "ar,bg",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for lock acquisition (give it 5 seconds)
    time.sleep(5)

    # Send SIGINT (Ctrl+C)
    proc.send_signal(signal.SIGINT)

    # Wait for process to exit
    proc.wait(timeout=10)

    # Verify lock file is cleaned up
    lock_file = Path(".translation_progress/locks/test.interrupt.net.lock")
    assert not lock_file.exists(), "Lock file not cleaned up after SIGINT"


@pytest.mark.skipif(not _SCALE_AVAILABLE, reason="Site profile test.scale.net.yaml not present")
@pytest.mark.parametrize("lang_count", [2, 3, 5])
def test_multi_language_scales(tmp_path, lang_count):
    """Test multi-language translation scales linearly (not exponentially)."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "test.md").write_text("# Test\n\nHello world.\n")

    output_dir = tmp_path / "output"

    langs = ["ar", "bg", "cs", "da", "de"][:lang_count]

    start = time.time()
    result = subprocess.run(
        [
            sys.executable, "-m", "src.cli",
            "--site", "test.scale.net",
            "--input", str(source_dir),
            "--output", str(output_dir),
            "--target-langs", ",".join(langs),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    duration = time.time() - start

    assert result.returncode == 0, f"Translation failed: {result.stderr}"

    # Should scale linearly: ~20s per language (not 300s per language)
    max_expected = lang_count * 30  # 30s per language with overhead
    assert duration < max_expected, \
        f"Duration {duration}s exceeds linear scaling ({max_expected}s)"
