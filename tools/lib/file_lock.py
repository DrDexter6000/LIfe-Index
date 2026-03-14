#!/usr/bin/env python3
"""
Life Index - File Locking Utility
==================================
Cross-platform file locking for concurrent access control.

Provides advisory locks to prevent race conditions when multiple
processes attempt to write to the same resources simultaneously.

Usage:
    from lib.file_lock import FileLock, LockTimeoutError

    # Basic usage with context manager
    with FileLock("/path/to/journals.lock"):
        # Critical section - only one process can execute
        write_journal(...)

    # With timeout (raise exception if not acquired within N seconds)
    try:
        with FileLock("/path/to/journals.lock", timeout=10.0):
            write_journal(...)
    except LockTimeoutError:
        print("Could not acquire lock within 10 seconds")

    # Non-blocking (immediate fail if lock not available)
    if FileLock("/path/to/journals.lock").try_lock():
        try:
            write_journal(...)
        finally:
            FileLock("/path/to/journals.lock").unlock()
    else:
        print("Resource is locked by another process")

Implementation:
    - Unix (Linux/macOS): Uses fcntl.flock() with LOCK_EX | LOCK_NB
    - Windows: Uses msvcrt.locking() with LK_NBLCK

Note:
    This is an advisory lock, not mandatory. All processes must
    cooperate by using FileLock for the lock to be effective.
"""

import os
import time
import platform
from pathlib import Path
from typing import Optional


class LockTimeoutError(TimeoutError):
    """Raised when a lock cannot be acquired within the specified timeout."""

    def __init__(self, lock_path: str, timeout: float):
        self.lock_path = lock_path
        self.timeout = timeout
        super().__init__(
            f"Could not acquire lock on '{lock_path}' within {timeout:.1f} seconds"
        )


class LockAcquisitionError(OSError):
    """Raised when a lock cannot be acquired in non-blocking mode."""

    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        super().__init__(f"Lock on '{lock_path}' is held by another process")


class FileLock:
    """
    Cross-platform file lock for concurrent access control.

    Uses advisory locking via:
    - Unix: fcntl.flock()
    - Windows: msvcrt.locking()

    Features:
    - Context manager support (with statement)
    - Configurable timeout
    - Non-blocking mode (try_lock)
    - Automatic cleanup on exception
    - Cross-platform (Windows, Linux, macOS)

    Attributes:
        lock_path: Path to the lock file
        timeout: Maximum time to wait for lock (seconds), None for no timeout
        poll_interval: Time between lock attempts when timeout is set

    Example:
        >>> lock = FileLock("/tmp/journals.lock", timeout=5.0)
        >>> with lock:
        ...     # Critical section
        ...     pass
    """

    def __init__(
        self,
        lock_path: str | Path,
        timeout: Optional[float] = None,
        poll_interval: float = 0.1,
    ):
        """
        Initialize the file lock.

        Args:
            lock_path: Path to the lock file. Will be created if it doesn't exist.
            timeout: Maximum seconds to wait for lock. None means wait forever.
            poll_interval: Seconds between lock attempts when timeout is set.
        """
        self.lock_path = Path(lock_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._file_handle: Optional[int] = None
        self._locked = False

    def _ensure_lock_file(self) -> None:
        """Ensure the lock file and its parent directory exist."""
        # Create parent directory if needed
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        # Create lock file if it doesn't exist
        if not self.lock_path.exists():
            self.lock_path.touch()

    def _acquire_unix(self, blocking: bool = True) -> bool:
        """Acquire lock on Unix systems using fcntl."""
        import fcntl

        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB

        try:
            fcntl.flock(self._file_handle, flags)
            return True
        except (IOError, OSError) as e:
            if not blocking and e.errno in (11, 35):  # EAGAIN, EWOULDBLOCK
                return False
            raise

    def _release_unix(self) -> None:
        """Release lock on Unix systems using fcntl."""
        import fcntl

        fcntl.flock(self._file_handle, fcntl.LOCK_UN)

    def _acquire_windows(self, blocking: bool = True) -> bool:
        """Acquire lock on Windows using msvcrt."""
        import msvcrt

        try:
            if blocking:
                # For blocking mode on Windows, we need to poll
                # msvcrt.locking doesn't support blocking waits
                start_time = time.time()
                while True:
                    try:
                        msvcrt.locking(self._file_handle, msvcrt.LK_NBLCK, 1)
                        return True
                    except OSError:
                        # Check timeout
                        if self.timeout is not None:
                            elapsed = time.time() - start_time
                            if elapsed >= self.timeout:
                                return False
                        time.sleep(self.poll_interval)
            else:
                # Non-blocking
                msvcrt.locking(self._file_handle, msvcrt.LK_NBLCK, 1)
                return True
        except OSError:
            return False

    def _release_windows(self) -> None:
        """Release lock on Windows using msvcrt."""
        import msvcrt

        # Seek to beginning and unlock
        os.lseek(self._file_handle, 0, os.SEEK_SET)
        msvcrt.locking(self._file_handle, msvcrt.LK_UNLCK, 1)

    def acquire(self, blocking: bool = True) -> bool:
        """
        Acquire the file lock.

        Args:
            blocking: If True, wait until lock is acquired.
                      If False, return immediately if lock unavailable.

        Returns:
            True if lock was acquired, False if non-blocking and lock unavailable.

        Raises:
            LockTimeoutError: If blocking with timeout and lock not acquired.
            LockAcquisitionError: If non-blocking and lock unavailable.
        """
        if self._locked:
            return True

        self._ensure_lock_file()

        # Open file for locking
        self._file_handle = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)

        system = platform.system()

        try:
            if system == "Windows":
                acquired = self._acquire_windows(blocking=blocking)
            else:  # Linux, macOS, and other Unix-like systems
                acquired = self._acquire_unix(blocking=blocking)

            if acquired:
                self._locked = True
                return True

            # Failed to acquire
            os.close(self._file_handle)
            self._file_handle = None

            if not blocking:
                raise LockAcquisitionError(str(self.lock_path))
            elif self.timeout is not None:
                raise LockTimeoutError(str(self.lock_path), self.timeout)
            return False

        except (LockTimeoutError, LockAcquisitionError):
            raise
        except Exception:
            # Clean up on unexpected error
            if self._file_handle is not None:
                try:
                    os.close(self._file_handle)
                except OSError:
                    pass
                self._file_handle = None
            raise

    def release(self) -> None:
        """Release the file lock."""
        if not self._locked or self._file_handle is None:
            return

        system = platform.system()

        try:
            if system == "Windows":
                self._release_windows()
            else:
                self._release_unix()
        finally:
            try:
                os.close(self._file_handle)
            except OSError:
                pass
            self._file_handle = None
            self._locked = False

    def try_lock(self) -> bool:
        """
        Attempt to acquire lock without blocking.

        Returns:
            True if lock was acquired, False if unavailable.
        """
        try:
            return self.acquire(blocking=False)
        except LockAcquisitionError:
            return False

    def unlock(self) -> None:
        """Release the lock (alias for release())."""
        self.release()

    def is_locked(self) -> bool:
        """Check if this instance holds the lock."""
        return self._locked

    def __enter__(self) -> "FileLock":
        """Enter context manager - acquire lock."""
        if self.timeout is not None:
            # Use polling for timeout on Unix as well
            start_time = time.time()
            while True:
                if self.try_lock():
                    return self
                elapsed = time.time() - start_time
                if elapsed >= self.timeout:
                    raise LockTimeoutError(str(self.lock_path), self.timeout)
                time.sleep(self.poll_interval)
        else:
            self.acquire(blocking=True)
            return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager - release lock."""
        self.release()

    def __del__(self) -> None:
        """Cleanup on garbage collection."""
        if self._locked:
            self.release()


def get_journals_lock_path() -> Path:
    """
    Get the lock file path for journal operations.

    Returns:
        Path to the journals.lock file in the Life-Index data directory.
    """
    from .config import USER_DATA_DIR

    return USER_DATA_DIR / ".cache" / "journals.lock"


def get_index_lock_path() -> Path:
    """
    Get the lock file path for index operations.

    Returns:
        Path to the index.lock file in the Life-Index data directory.
    """
    from .config import USER_DATA_DIR

    return USER_DATA_DIR / ".cache" / "index.lock"


# Convenience functions for common use cases
def with_journals_lock(func, *args, timeout: float = 30.0, **kwargs):
    """
    Execute a function with the journals lock held.

    Args:
        func: Function to execute
        timeout: Lock acquisition timeout in seconds
        *args, **kwargs: Arguments to pass to func

    Returns:
        Result of func(*args, **kwargs)

    Raises:
        LockTimeoutError: If lock cannot be acquired within timeout
    """
    with FileLock(get_journals_lock_path(), timeout=timeout):
        return func(*args, **kwargs)


def with_index_lock(func, *args, timeout: float = 60.0, **kwargs):
    """
    Execute a function with the index lock held.

    Args:
        func: Function to execute
        timeout: Lock acquisition timeout in seconds
        *args, **kwargs: Arguments to pass to func

    Returns:
        Result of func(*args, **kwargs)

    Raises:
        LockTimeoutError: If lock cannot be acquired within timeout
    """
    with FileLock(get_index_lock_path(), timeout=timeout):
        return func(*args, **kwargs)
