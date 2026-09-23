"""Windows-safe subprocess helpers for unattended campaign processes."""
from __future__ import annotations

import subprocess


def hidden_creation_flags(*, new_process_group: bool = False) -> int:
    """Return flags that prevent console flashes while preserving tree control."""
    if not hasattr(subprocess, "CREATE_NO_WINDOW"):
        return 0
    flags = subprocess.CREATE_NO_WINDOW
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


def hidden_subprocess_kwargs(*, new_process_group: bool = False) -> dict:
    """Keyword arguments shared by campaign Git and worker launches."""
    kwargs = {"creationflags": hidden_creation_flags(new_process_group=new_process_group)}
    startupinfo = hidden_startupinfo()
    if startupinfo is not None:
        kwargs["startupinfo"] = startupinfo
    return kwargs
