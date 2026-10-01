"""
Run untrusted-file parsing (PDF, Word, images) in a separate process with a time limit.

A crafted file can make a parser spin for minutes. In the web process that would freeze every page for every user
(the upload handlers are async, so they share one event loop). Here the parse happens in a child process: if it
runs past the limit, the child is killed and the caller gets ParseTimeout. The function must be importable at module
level (it is pickled by name), and so must its arguments and result.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import threading

PARSE_SECONDS = float(os.environ.get("PARSE_TIMEOUT_SECONDS", "10") or 10)
# At most this many parses at once across the whole site; more are turned away (ParseBusy) instead of queueing,
# so a flood of uploads can't occupy every CPU. Each child also gets hard CPU-time and memory ceilings.
MAX_PARALLEL = max(1, int(os.environ.get("PARSE_MAX_PARALLEL", "2") or 2))
CHILD_MEMORY_MB = 512
_slots = threading.BoundedSemaphore(MAX_PARALLEL)

try:
    _CTX = mp.get_context("forkserver")      # clean server process: no locks inherited from the web server's threads
except ValueError:                           # pragma: no cover - platforms without forkserver
    _CTX = mp.get_context("spawn")


class ParseTimeout(Exception):
    pass


class ParseBusy(ParseTimeout):
    """Too many files are being read right now. A subclass of ParseTimeout, so callers can treat both alike."""


def _limit_child(seconds: float) -> None:
    try:
        import resource
        cpu = int(seconds) + 2
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        mem = CHILD_MEMORY_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    except (ImportError, ValueError, OSError):       # pragma: no cover - not available on this platform
        pass


def _child(conn, fn, args, kwargs, seconds):
    _limit_child(seconds)
    try:
        conn.send(("ok", fn(*args, **kwargs)))
    except BaseException as e:               # noqa: BLE001 - hand any failure back to the parent
        try:
            conn.send(("err", e))
        except Exception:                    # noqa: BLE001 - the exception itself wasn't picklable
            conn.send(("err", RuntimeError(f"{type(e).__name__}: {e}")))
    finally:
        conn.close()


def run(fn, *args, timeout: float | None = None, **kwargs):
    """fn(*args, **kwargs) in a child process. Raises ParseTimeout if it takes longer than `timeout` seconds;
    re-raises whatever fn raised."""
    limit = PARSE_SECONDS if timeout is None else timeout
    if not _slots.acquire(timeout=2):
        raise ParseBusy("too many files are being read right now")
    try:
        return _run(fn, args, kwargs, limit)
    finally:
        _slots.release()


def _run(fn, args, kwargs, limit):
    parent, child = _CTX.Pipe(duplex=False)
    proc = _CTX.Process(target=_child, args=(child, fn, args, kwargs, limit), daemon=True)
    proc.start()
    child.close()
    try:
        if not parent.poll(limit):
            raise ParseTimeout(f"parsing took longer than {limit:g} seconds")
        kind, value = parent.recv()
    except EOFError:
        raise RuntimeError("the parser stopped unexpectedly")
    finally:
        parent.close()
        if proc.is_alive():
            proc.kill()
        proc.join(1)
    if kind == "err":
        raise value
    return value


async def run_async(fn, *args, timeout: float | None = None, **kwargs):
    """Same as run(), without blocking the event loop while waiting."""
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(lambda: run(fn, *args, timeout=timeout, **kwargs))
