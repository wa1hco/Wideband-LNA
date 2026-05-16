from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextmanager
def process_guard(lock_path: Path, stale_seconds: int) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    now = _utc_now()

    if lock_path.exists():
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}

        existing_pid = int(payload.get("pid", -1))
        started_raw = str(payload.get("started_utc", ""))
        started = None
        try:
            started = datetime.fromisoformat(started_raw)
        except Exception:
            started = None

        is_stale = False
        if started is not None:
            is_stale = now - started > timedelta(seconds=max(1, stale_seconds))

        if _is_process_alive(existing_pid) and not is_stale:
            raise RuntimeError(
                f"Another bench process appears active (pid={existing_pid}). "
                f"Lock file: {lock_path}"
            )

        # Clear stale/dead lock so this process can proceed.
        lock_path.unlink(missing_ok=True)

    payload = {
        "pid": pid,
        "started_utc": now.isoformat(),
    }

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(lock_path), flags)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        yield
    finally:
        try:
            if lock_path.exists():
                current = json.loads(lock_path.read_text(encoding="utf-8"))
                if int(current.get("pid", -1)) == pid:
                    lock_path.unlink(missing_ok=True)
        except Exception:
            # Best-effort cleanup only.
            pass
