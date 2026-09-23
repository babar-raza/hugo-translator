"""Windows-safe subprocess helpers for unattended campaign processes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def hidden_python_executable() -> str:
    """Use pythonw for campaign children so Windows never allocates conhost."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate) if candidate.is_file() else sys.executable


def hidden_creation_flags(*, new_process_group: bool = False, no_window: bool = True) -> int:
    """Return flags that prevent console flashes while preserving tree control.

    ``no_window`` (``CREATE_NO_WINDOW``) defaults on for lightweight children
    (git, calibration, journal merges). It must stay off for workers that may
    host Fortran/MKL-backed local models: a fully console-less process was
    already tried historically for those and still produced a
    ``forrtl: error (200): program aborting due to window-CLOSE event`` abort
    -- see test_shard_launcher_process_lifecycle.py. ``STARTF_USESHOWWINDOW``/
    ``SW_HIDE`` (hidden_startupinfo) still hides the window in that case
    without removing the console the runtime expects to find.
    """
    if not hasattr(subprocess, "CREATE_NO_WINDOW"):
        return 0
    flags = subprocess.CREATE_NO_WINDOW if no_window else 0
    if new_process_group:
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    return flags


def hidden_startupinfo() -> subprocess.STARTUPINFO | None:
    """Hide a Windows console even when a native child ignores inherited state."""
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info


def hidden_subprocess_kwargs(*, new_process_group: bool = False, no_window: bool = True) -> dict:
    """Keyword arguments shared by campaign Git and worker launches."""
    kwargs = {
        "creationflags": hidden_creation_flags(
            new_process_group=new_process_group, no_window=no_window
        )
    }
    startupinfo = hidden_startupinfo()
    if startupinfo is not None:
        kwargs["startupinfo"] = startupinfo
    return kwargs
