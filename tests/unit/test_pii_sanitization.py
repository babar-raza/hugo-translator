"""Unit tests for PII sanitization in system info collection (TC-BM-10)."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from src.benchmarking.system_info import SystemInfoCollector


def test_username_sanitized_in_paths():
    """Test that usernames in paths are sanitized."""
    collector = SystemInfoCollector()

    # Test Windows-style paths
    test_cases_windows = [
        ("C:/Users/john.doe/Documents", "C:/Users/<user>/Documents"),
        ("C:\\Users\\alice\\Projects", "C:/Users/<user>/Projects"),
        ("D:/Users/bob123/file.txt", "D:/Users/<user>/file.txt"),
    ]

    for input_path, expected in test_cases_windows:
        sanitized = collector._sanitize_string(input_path)
        assert sanitized == expected, f"Failed to sanitize: {input_path}"
        assert "john.doe" not in sanitized
        assert "alice" not in sanitized
        assert "bob123" not in sanitized


def test_home_directory_sanitized():
    """Test that home directory paths are sanitized."""
    collector = SystemInfoCollector()

    # Test Linux/macOS style paths
    test_cases_unix = [
        ("/home/username/project", "/home/<user>/project"),
        ("/home/alice.smith/.config", "/home/<user>/.config"),
        ("/home/bob/Documents/file.md", "/home/<user>/Documents/file.md"),
    ]

    for input_path, expected in test_cases_unix:
        sanitized = collector._sanitize_string(input_path)
        assert sanitized == expected, f"Failed to sanitize: {input_path}"
        assert "username" not in sanitized
        assert "alice.smith" not in sanitized
        assert "bob" not in sanitized


def test_onedrive_paths_sanitized():
    """Test that OneDrive paths are sanitized."""
    collector = SystemInfoCollector()

    test_cases = [
        ("C:/Users/john/OneDrive/Documents/project", "C:/Users/<user>/<user>/Documents/project"),
        ("OneDrive/Documents/file.txt", "<user>/Documents/file.txt"),
        ("C:\\Users\\alice\\OneDrive\\Documents\\test", "C:/Users/<user>/<user>/Documents/test"),
    ]

    for input_path, expected in test_cases:
        sanitized = collector._sanitize_string(input_path)
        assert sanitized == expected, f"Failed to sanitize: {input_path}"


def test_cross_platform_path_sanitization():
    """Test that paths are normalized to forward slashes."""
    collector = SystemInfoCollector()

    # All backslashes should become forward slashes
    test_cases = [
        ("C:\\Users\\test\\file.txt", "C:/Users/<user>/file.txt"),
        ("C:/Users/test/file.txt", "C:/Users/<user>/file.txt"),
        ("C:\\Users\\test\\nested\\path\\file.txt", "C:/Users/<user>/nested/path/file.txt"),
    ]

    for input_path, expected in test_cases:
        sanitized = collector._sanitize_string(input_path)
        assert sanitized == expected, f"Path normalization failed: {input_path}"
        # All paths should use forward slashes
        assert "\\" not in sanitized


def test_case_insensitive_sanitization():
    """Test that sanitization is case-insensitive."""
    collector = SystemInfoCollector()

    test_cases = [
        ("c:/users/john/file.txt", "c:/users/<user>/file.txt"),
        ("C:/USERS/JOHN/file.txt", "C:/USERS/<user>/file.txt"),
        ("/HOME/username/file.txt", "/HOME/<user>/file.txt"),
        ("/Home/username/file.txt", "/Home/<user>/file.txt"),
    ]

    for input_path, expected in test_cases:
        sanitized = collector._sanitize_string(input_path)
        assert sanitized == expected, f"Case-insensitive sanitization failed: {input_path}"


def test_empty_string_handling():
    """Test that empty strings are handled gracefully."""
    collector = SystemInfoCollector()

    assert collector._sanitize_string("") == ""
    assert collector._sanitize_string(None) is None


def test_no_username_in_path():
    """Test that paths without usernames are unchanged."""
    collector = SystemInfoCollector()

    test_cases = [
        "/var/log/system.log",
        "C:/Program Files/Application/file.exe",
        "/opt/software/bin/tool",
        "relative/path/to/file.txt",
    ]

    for path in test_cases:
        sanitized = collector._sanitize_string(path)
        # Should normalize slashes but not change content
        expected = path.replace("\\", "/")
        assert sanitized == expected, f"Should not modify: {path}"


def test_actual_username_not_leaked():
    """Test that the actual system username is sanitized."""
    collector = SystemInfoCollector()

    try:
        # Get actual system username
        actual_username = os.getlogin()
    except OSError:
        # Some environments don't support getlogin(), skip test
        pytest.skip("Cannot get system username in this environment")

    # Test that actual username in path gets sanitized
    test_paths = [
        f"C:/Users/{actual_username}/Documents",
        f"/home/{actual_username}/project",
        f"C:\\Users\\{actual_username}\\file.txt",
    ]

    for path in test_paths:
        sanitized = collector._sanitize_string(path)
        assert actual_username not in sanitized, f"Username leaked in: {sanitized}"
        assert "<user>" in sanitized


def test_actual_home_directory_not_leaked():
    """Test that the actual home directory path is sanitized."""
    collector = SystemInfoCollector()

    try:
        # Get actual home directory
        home_path = str(Path.home())
    except Exception:
        pytest.skip("Cannot get home directory in this environment")

    # Sanitize the home path
    sanitized = collector._sanitize_string(home_path)

    # Extract username from home path
    # Windows: C:/Users/username
    # Unix: /home/username
    if "Users" in home_path or "users" in home_path:
        # Windows
        parts = home_path.replace("\\", "/").split("/")
        if "Users" in parts or "users" in parts:
            user_idx = next(i for i, p in enumerate(parts) if p.lower() == "users")
            if user_idx + 1 < len(parts):
                username = parts[user_idx + 1]
                assert username not in sanitized, f"Username '{username}' leaked in sanitized path"
    elif "/home/" in home_path:
        # Unix
        username = home_path.split("/home/")[1].split("/")[0]
        assert username not in sanitized, f"Username '{username}' leaked in sanitized path"


def test_multiple_usernames_in_path():
    """Test that multiple username patterns are all sanitized."""
    collector = SystemInfoCollector()

    # Path with multiple user segments (unlikely but should handle)
    test_path = "/home/alice/shared/home/bob/file.txt"
    sanitized = collector._sanitize_string(test_path)

    # Both should be sanitized
    assert "alice" not in sanitized
    assert "bob" not in sanitized
    assert sanitized == "/home/<user>/shared/home/<user>/file.txt"


def test_system_info_fields_sanitized():
    """Test that SystemInfo fields are sanitized when collected."""
    collector = SystemInfoCollector()
    system_info = collector.collect()

    # Get all string fields from SystemInfo
    fields_to_check = [
        system_info.python_version,
        system_info.cpu_model,
        system_info.gpu_model,
        system_info.os_name,
        system_info.platform_system,
        system_info.platform_release,
        system_info.os_version,
        system_info.python_implementation,
    ]

    # Get actual username if possible
    try:
        actual_username = os.getlogin()
        has_username = True
    except OSError:
        has_username = False

    # Get actual home directory if possible
    try:
        home_path = str(Path.home())
        has_home = True
    except Exception:
        has_home = False

    # Check that no field contains actual username or home path
    for field in fields_to_check:
        if field is None:
            continue

        field_str = str(field)

        if has_username:
            assert actual_username not in field_str, f"Username leaked in field: {field}"

        if has_home:
            # Home path might be in field, but username portion should be sanitized
            if home_path in field_str:
                # This should not happen - sanitization should remove it
                pytest.fail(f"Full home path leaked in field: {field}")


def test_sanitization_preserves_structure():
    """Test that sanitization preserves path structure."""
    collector = SystemInfoCollector()

    test_cases = [
        # Should preserve directory structure
        ("C:/Users/test/dir1/dir2/file.txt", "C:/Users/<user>/dir1/dir2/file.txt"),
        ("/home/user/a/b/c/d.txt", "/home/<user>/a/b/c/d.txt"),
        # Should preserve file extensions
        ("C:/Users/test/doc.pdf", "C:/Users/<user>/doc.pdf"),
        # Should preserve other path components
        ("/home/alice/projects/myapp/src/main.py", "/home/<user>/projects/myapp/src/main.py"),
    ]

    for input_path, expected in test_cases:
        sanitized = collector._sanitize_string(input_path)
        assert sanitized == expected

        # Verify structure is preserved
        input_parts = input_path.replace("\\", "/").split("/")
        sanitized_parts = sanitized.split("/")

        # Should have same number of parts
        assert len(input_parts) == len(sanitized_parts)

        # File extension should be preserved
        if "." in input_parts[-1]:
            assert input_parts[-1].split(".")[-1] == sanitized_parts[-1].split(".")[-1]
