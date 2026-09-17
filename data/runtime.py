"""Bound background work so slow upstream services cannot accumulate threads."""
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from pathlib import Path
import threading


class RefreshTasks:
    """One bounded executor and at most one outstanding job per fixed task key."""

    def __init__(self, max_workers=3):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Provider")
        self._lock = threading.Lock()
        self._jobs = {}

    def submit_once(self, key, fn, *args):
        with self._lock:
            previous = self._jobs.get(key)
            if previous is not None and not previous.done():
                return previous
            future = self._executor.submit(fn, *args)
            self._jobs[key] = future
            return future

    def cancel_pending(self):
        with self._lock:
            for future in self._jobs.values():
                future.cancel()  # Running jobs stay tracked until they finish.

    def shutdown(self):
        self._executor.shutdown(wait=True, cancel_futures=True)


def serialized(fn):
    """Serialize cache-check + refresh so concurrent callers share cached work."""
    lock = threading.Lock()

    @wraps(fn)
    def wrapped(*args, **kwargs):
        with lock:
            return fn(*args, **kwargs)
    return wrapped


def memory_usage():
    """Linux resident memory and thread count, without a profiling dependency."""
    result = {"threads": threading.active_count()}
    try:
        fields = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
        for source, target in (("VmRSS", "rss_mb"), ("VmHWM", "peak_rss_mb")):
            result[target] = round(int(fields[source].split()[0]) / 1024, 1)
    except (OSError, KeyError, ValueError):
        pass  # /proc is unavailable in Windows development environments.
    return result
