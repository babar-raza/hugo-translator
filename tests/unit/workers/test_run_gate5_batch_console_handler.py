"""TC-PORT-LLM-012: run_gate5_batch.py must install a real Win32 console
control handler, not rely on the controller's ineffective
SetConsoleCtrlHandler(NULL, TRUE) call -- see
test_shard_launcher_process_lifecycle.py for the companion launcher-side fix
and the full root-cause writeup.
"""

import sys

import pytest

from scripts.campaign import run_gate5_batch


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 console API")
def test_installs_a_real_handler_that_reports_success(monkeypatch):
    import ctypes

    calls = []

    def _fake_set_console_ctrl_handler(callback, add):
        calls.append((callback, add))
        return 1  # Windows BOOL TRUE: installed successfully

    monkeypatch.setattr(
        ctypes.windll.kernel32, "SetConsoleCtrlHandler", _fake_set_console_ctrl_handler
    )

    run_gate5_batch._install_console_control_handler()

    assert len(calls) == 1
    callback, add = calls[0]
    assert add == 1, "must ADD a handler, not remove one"
    assert callback is not None


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 console API")
def test_the_installed_handler_reports_every_event_as_handled(monkeypatch):
    """The whole point: Windows must never fall through to the Fortran
    runtime's default terminate action for CTRL_CLOSE/LOGOFF/SHUTDOWN, which
    SetConsoleCtrlHandler(NULL, TRUE) does not cover. Returning TRUE for
    every event type is the actual fix.
    """
    import ctypes

    installed = {}

    def _fake_set_console_ctrl_handler(callback, add):
        installed["callback"] = callback
        return 1

    monkeypatch.setattr(
        ctypes.windll.kernel32, "SetConsoleCtrlHandler", _fake_set_console_ctrl_handler
    )

    run_gate5_batch._install_console_control_handler()

    handler = installed["callback"]
    # CTRL_C_EVENT=0, CTRL_BREAK_EVENT=1, CTRL_CLOSE_EVENT=2,
    # CTRL_LOGOFF_EVENT=5, CTRL_SHUTDOWN_EVENT=6 -- the last three are the
    # ones SetConsoleCtrlHandler(NULL, TRUE) never protected against.
    for event in (0, 1, 2, 5, 6):
        assert handler(event) == 1, f"event {event} was not reported as handled"


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 console API")
def test_raises_if_installation_fails(monkeypatch):
    import ctypes

    monkeypatch.setattr(
        ctypes.windll.kernel32, "SetConsoleCtrlHandler", lambda callback, add: 0
    )

    with pytest.raises(OSError):
        run_gate5_batch._install_console_control_handler()


def test_is_a_no_op_off_windows(monkeypatch):
    monkeypatch.setattr(run_gate5_batch.sys, "platform", "linux")

    run_gate5_batch._install_console_control_handler()  # must not raise
