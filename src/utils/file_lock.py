"""
RES-08: Cross-platform file-based locking mechanism.

Provides file-based locks for preventing concurrent translations of the same site.
Works on both Unix/Linux (fcntl) and Windows (msvcrt).
"""

import json
import os
import socket
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def diagnose_lock(site_id: str) -> None:
    r"""
    Print basic lock diagnostics for a site.

    TC2: Lite version - shows lock status, age, PID, and recommendations.

    Args:
        site_id: Site identifier

    Output format:
        =====================================
        Lock Diagnostics: kb.aspose.net
        =====================================
        Lock Path: C:\\Users\\...\\locks\\kb.aspose.net.lock
        Lock Exists: Yes
        Lock Age: 1234 seconds (20.6 minutes)

        Lock Content:
        - Holder PID: 12345 (if readable)
        - Holder Process: <dead> / python.exe (RUNNING)

        Recommendation:
        - Stale lock detected: Run 'unlock --site kb.aspose.net --yes'
        - Live process: Wait or investigate why lock not released
        =====================================
    """
    # Import here to avoid circular dependency
    from ..translation_engine.engine import get_site_lock_path

    lock_file = get_site_lock_path(site_id)

    print("=" * 60)
    print(f"Lock Diagnostics: {site_id}")
    print("=" * 60)
    print(f"Lock Path: {lock_file}")

    # Check existence
    if not lock_file.exists():
        print("Lock Exists: No")
        print("\nNo lock file found. Site is not locked.")
        print("=" * 60)
        return

    print("Lock Exists: Yes")

    # Check age
    try:
        stat = lock_file.stat()
        age = time.time() - stat.st_mtime
        print(f"Lock Age: {age:.0f} seconds ({age/60:.1f} minutes)")
    except Exception as e:
        print(f"Lock Age: Unable to stat ({e})")
        age = 0

    # Try to read content
    print("\nLock Content:")
    try:
        with open(lock_file, 'r') as f:
            content = f.read().strip()

        # Try JSON format first, fallback to text
        try:
            data = json.loads(content)
            pid = data.get('pid')
            hostname = data.get('hostname', 'unknown')
        except json.JSONDecodeError:
            pid = int(content)
            hostname = 'unknown'

        # Check if process alive (create temp lock to use helper method)
        temp_lock = FileLock(lock_file)
        is_alive = temp_lock._is_process_alive(pid)
        status = "RUNNING" if is_alive else "<dead>"
        print(f"- Holder PID: {pid}")
        print(f"- Holder Host: {hostname}")
        print(f"- Holder Process: {status}")

        print("\nRecommendation:")
        if is_alive:
            print(f"- Process {pid} is still running")
            print("- Wait for it to complete or investigate why lock not released")
        else:
            print(f"- Process {pid} is dead (stale lock)")
            print(f"- Run: python -m src.cli unlock --site {site_id} --yes")

    except PermissionError:
        print("- Cannot read (PermissionError)")
        print("\nRecommendation:")
        if age > 600:  # 10 minutes
            print(f"- Lock is old ({age/60:.1f} minutes), likely stale")
            print(f"- Run: python -m src.cli unlock --site {site_id} --yes --force")
        else:
            print("- Lock is recent, may be held by active process")
            print("- Wait a few minutes and check again")

    print("=" * 60)


class LockError(Exception):
    """Raised when lock cannot be acquired."""
    pass


class FileLock:
    """
    Cross-platform file-based lock.

    Uses:
    - fcntl.flock() on Unix/Linux/Mac
    - msvcrt.locking() on Windows

    Features:
    - Timeout support
    - Automatic cleanup
    - Context manager interface
    - Stale lock detection

    Usage:
        # As context manager (recommended)
        with FileLock(lock_file) as lock:
            # Do work while holding lock
            pass

        # Manual acquire/release
        lock = FileLock(lock_file)
        lock.acquire()
        try:
            # Do work
        finally:
            lock.release()
    """

    def __init__(
        self,
        lock_file: Path,
        timeout: float = 300.0,
        poll_interval: float = 1.0
    ):
        """
        Initialize file lock.

        Args:
            lock_file: Path to lock file
            timeout: Max seconds to wait for lock (0 = no wait)
            poll_interval: Seconds between lock attempts
        """
        self.lock_file = Path(lock_file)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._fd: Optional[int] = None
        self._locked = False

        # Create lock directory
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)

    def acquire(self, blocking: bool = True) -> bool:
        """
        Acquire the lock.

        Args:
            blocking: Wait for lock if True, return immediately if False

        Returns:
            True if lock acquired, False otherwise

        Raises:
            LockError: If lock cannot be acquired within timeout (blocking mode only)
        """
        if self._locked:
            return True

        start_time = time.time()

        while True:
            try:
                # Open lock file
                self._fd = os.open(
                    str(self.lock_file),
                    os.O_CREAT | os.O_WRONLY | os.O_TRUNC
                )

                # Try to acquire lock
                if sys.platform == 'win32':  # Windows
                    import msvcrt
                    msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                else:  # Unix/Linux/Mac
                    import fcntl
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

                # TC2: Write JSON metadata to lock file
                metadata = {
                    'pid': os.getpid(),
                    'hostname': socket.gethostname(),
                    'created': datetime.now().isoformat(),
                    'format_version': '1.0'
                }
                os.write(self._fd, json.dumps(metadata, indent=2).encode())
                os.fsync(self._fd)

                self._locked = True
                logger.debug(f"Lock acquired: {self.lock_file}")
                return True

            except (IOError, OSError) as e:
                # Lock is held by another process
                if self._fd is not None:
                    try:
                        os.close(self._fd)
                    except OSError:
                        pass
                    self._fd = None

                # Non-blocking mode
                if not blocking:
                    return False

                # Check timeout
                elapsed = time.time() - start_time

                # timeout=0 means fail immediately
                if self.timeout == 0:
                    raise LockError(
                        f"Failed to acquire lock (no wait): {self.lock_file}"
                    )

                if elapsed >= self.timeout:
                    # Check if lock is stale
                    if self._is_stale_lock():
                        logger.warning("Stale lock detected, removing...")
                        self._remove_stale_lock()
                        continue  # Try again

                    raise LockError(
                        f"Failed to acquire lock after {elapsed:.1f}s: {self.lock_file}"
                    )

                # Wait and retry
                time.sleep(self.poll_interval)

    def release(self) -> None:
        """Release the lock."""
        if not self._locked:
            return

        try:
            if self._fd is not None:
                # Release lock
                if sys.platform == 'win32':  # Windows
                    import msvcrt
                    try:
                        msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass  # May already be unlocked
                else:  # Unix/Linux/Mac
                    import fcntl
                    fcntl.flock(self._fd, fcntl.LOCK_UN)

                os.close(self._fd)
                self._fd = None

            # Remove lock file
            if self.lock_file.exists():
                try:
                    self.lock_file.unlink()
                except OSError:
                    pass  # May have been removed

            self._locked = False
            logger.debug(f"Lock released: {self.lock_file}")

        except Exception as e:
            logger.error(f"Error releasing lock: {e}")

    def _is_process_alive(self, pid: int) -> bool:
        """
        Check if process with given PID is running.

        Args:
            pid: Process ID to check

        Returns:
            True if process is alive, False otherwise
        """
        if sys.platform == 'win32':
            try:
                import subprocess
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                return str(pid) in result.stdout
            except Exception:
                return False  # Conservative: assume dead
        else:
            # Unix: send signal 0 - doesn't kill, just checks existence
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def _is_stale_lock(self) -> bool:
        """
        Check if lock file is stale.

        TC2: Handles both legacy text format (just PID) and new JSON format.
        Uses age-based fallback heuristic if lock file is unreadable.

        Returns:
            True if lock appears stale
        """
        try:
            if not self.lock_file.exists():
                return False

            # Read lock file
            with open(self.lock_file, 'r') as f:
                content = f.read().strip()

            # Try JSON format first (new format)
            try:
                data = json.loads(content)
                pid = data['pid']
                created = data.get('created')
                # Can add more sophisticated staleness checks with timestamp
            except json.JSONDecodeError:
                # Legacy text format - just PID as integer
                pid = int(content)
                created = None

            # Check if process exists
            is_alive = self._is_process_alive(pid)
            if not is_alive:
                logger.info(f"Lock is stale: PID {pid} no longer running")
                return True

            return False

        except PermissionError:
            # Cannot read lock file - likely held by external process
            # TC2: Fallback to age-based heuristic
            logger.warning("Lock file unreadable (PermissionError), checking age...")

            try:
                stat = self.lock_file.stat()
                lock_age = time.time() - stat.st_mtime

                # If lock older than 2x timeout, treat as stale
                stale_threshold = self.timeout * 2
                if lock_age > stale_threshold:
                    logger.warning(
                        f"Lock file age ({lock_age:.0f}s) exceeds 2x timeout ({stale_threshold:.0f}s). "
                        f"Treating as stale despite PermissionError."
                    )
                    return True

                logger.info(
                    f"Lock file age ({lock_age:.0f}s) within threshold ({stale_threshold:.0f}s). "
                    f"Assuming lock is valid."
                )
                return False

            except Exception as stat_error:
                logger.warning(f"Cannot stat lock file: {stat_error}")
                return False  # Conservative: assume valid

        except Exception as e:
            logger.warning(f"Error checking stale lock: {e}")
            return False  # Conservative: assume lock is valid

    def _remove_stale_lock(self) -> None:
        """Force remove stale lock file."""
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
                logger.info(f"Removed stale lock: {self.lock_file}")
        except Exception as e:
            logger.error(f"Error removing stale lock: {e}")

    def force_unlock(self, check_pid: bool = True) -> bool:
        """
        Force remove lock file.

        TC2: Provides manual recovery from stuck locks with safety checks.

        Args:
            check_pid: If True, refuse to unlock if holder process is alive

        Returns:
            True if lock removed, False if refused (live process)

        Raises:
            LockError: If lock removal fails
        """
        if not self.lock_file.exists():
            logger.info("Lock file does not exist, nothing to unlock")
            return True

        # Safety check: Verify process not alive (unless forced)
        if check_pid:
            try:
                with open(self.lock_file, 'r') as f:
                    content = f.read().strip()

                # Parse PID from either format
                try:
                    data = json.loads(content)
                    pid = data['pid']
                    hostname = data.get('hostname', 'unknown')
                except json.JSONDecodeError:
                    pid = int(content)
                    hostname = 'unknown'

                # Check if process alive
                if self._is_process_alive(pid):
                    logger.error(
                        f"Refusing to force unlock: Process {pid} on {hostname} is still running. "
                        f"Use --force to override (DANGEROUS)."
                    )
                    return False

            except PermissionError:
                # Cannot read - assume external holder, allow removal
                logger.warning("Cannot read lock file due to PermissionError, proceeding with force unlock")
            except Exception as e:
                logger.warning(f"Error checking lock holder: {e}, proceeding with force unlock")

        # Remove lock file
        try:
            self.lock_file.unlink()
            logger.info(f"Force unlocked: {self.lock_file}")
            return True
        except Exception as e:
            raise LockError(f"Failed to remove lock file: {e}")

    def __enter__(self) -> 'FileLock':
        """Context manager entry."""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit."""
        self.release()
        return False

    def __del__(self):
        """Cleanup on deletion."""
        self.release()
