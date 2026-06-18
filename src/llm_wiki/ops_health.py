from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable
import urllib.error
import urllib.request

from .config import Settings, load_settings
from .requests_store import count_requests_by_status, list_worker_state


STATUS_SCORE = {"OK": 0, "WARN": 1, "CRITICAL": 2}
PRIMARY_BACKUP_PATTERNS = {
    "postgres_dump": "llm-wiki-app-db-*.sql",
    "object_manifest": "llm-wiki-objects-*.json",
    "object_archive": "llm-wiki-objects-*.tar.gz",
    "backup_run": "llm-wiki-backup-run-*.json",
}


def build_health_summary(
    settings: Settings | None = None,
    *,
    api_url: str | None = None,
    backup_dir: Path = Path("/backups"),
    codex_login_log: Path = Path("/backups/codex-login-status.log"),
    now: datetime | None = None,
    queued_warn: int = 10,
    failed_warn: int = 1,
    backup_warn_hours: int = 30,
    backup_critical_hours: int = 48,
    codex_login_warn_minutes: int = 90,
    codex_login_critical_minutes: int = 180,
    request_counter: Callable[[Settings | None], list[dict]] | None = None,
    worker_lister: Callable[[Settings | None], list[dict]] | None = None,
    url_checker: Callable[[str], tuple[bool, str]] | None = None,
) -> dict:
    resolved = settings or load_settings()
    current_time = _aware(now or datetime.now(timezone.utc))
    checks: list[dict] = []
    counts: list[dict] = []
    workers: list[dict] = []

    if api_url:
        checker = url_checker or _check_url
        ok, detail = checker(api_url)
        _add_check(
            checks,
            name="api_health",
            status="OK" if ok else "CRITICAL",
            detail=detail,
        )

    try:
        counter = request_counter or count_requests_by_status
        counts = counter(resolved)
        _add_check(checks, name="db", status="OK", detail="database reachable")
    except Exception as exc:  # pragma: no cover - exact driver exceptions vary
        _add_check(checks, name="db", status="CRITICAL", detail=f"database check failed: {type(exc).__name__}")

    if counts:
        count_map = {row["status"]: int(row["count"]) for row in counts}
        queued = count_map.get("queued", 0)
        failed = count_map.get("failed", 0)
        status = "WARN" if queued > queued_warn or failed >= failed_warn else "OK"
        _add_check(
            checks,
            name="request_queue",
            status=status,
            detail=f"queued={queued} failed={failed}",
            data={"queued": queued, "failed": failed},
        )

    try:
        lister = worker_lister or list_worker_state
        workers = lister(resolved)
        _add_worker_check(checks, workers, resolved, current_time)
    except Exception as exc:  # pragma: no cover - exact driver exceptions vary
        _add_check(checks, name="worker_heartbeat", status="CRITICAL", detail=f"worker check failed: {type(exc).__name__}")

    _add_backup_check(
        checks,
        backup_dir=backup_dir,
        now=current_time,
        warn_hours=backup_warn_hours,
        critical_hours=backup_critical_hours,
    )
    _add_codex_login_check(
        checks,
        log_path=codex_login_log,
        now=current_time,
        warn_minutes=codex_login_warn_minutes,
        critical_minutes=codex_login_critical_minutes,
    )

    status = _overall_status(checks)
    return {
        "status": status,
        "generated_at": current_time.isoformat(),
        "checks": checks,
    }


def health_exit_code(status: str) -> int:
    if status == "CRITICAL":
        return 2
    if status == "WARN":
        return 1
    return 0


def _add_worker_check(checks: list[dict], workers: list[dict], settings: Settings, now: datetime) -> None:
    if not workers:
        _add_check(checks, name="worker_heartbeat", status="CRITICAL", detail="no worker heartbeat rows")
        return
    latest = workers[0]
    updated_at = _aware(latest.get("updated_at"))
    if not updated_at:
        _add_check(checks, name="worker_heartbeat", status="CRITICAL", detail="latest worker row has no updated_at")
        return
    age_seconds = max(0, int((now - updated_at).total_seconds()))
    warn_seconds = max(settings.worker_heartbeat_interval * 2, 30)
    critical_seconds = max(settings.worker_heartbeat_interval * 4, 60)
    status = "OK"
    if age_seconds > critical_seconds:
        status = "CRITICAL"
    elif age_seconds > warn_seconds:
        status = "WARN"
    value = latest.get("value") if isinstance(latest.get("value"), dict) else {}
    state = value.get("state") or "unknown"
    worker_id = value.get("worker_id") or latest.get("key")
    _add_check(
        checks,
        name="worker_heartbeat",
        status=status,
        detail=f"latest worker {worker_id} state={state} age_seconds={age_seconds}",
        data={"age_seconds": age_seconds, "state": state},
    )


def _add_backup_check(
    checks: list[dict],
    *,
    backup_dir: Path,
    now: datetime,
    warn_hours: int,
    critical_hours: int,
) -> None:
    latest_by_kind = {
        kind: _newest_matching_file(backup_dir, [pattern]) for kind, pattern in PRIMARY_BACKUP_PATTERNS.items()
    }
    missing = [kind for kind, path in latest_by_kind.items() if path is None]
    if missing:
        _add_check(
            checks,
            name="backup_age",
            status="CRITICAL",
            detail=f"missing primary backup artifacts in {backup_dir}: {', '.join(missing)}",
            data={"missing": missing},
        )
        return
    assert all(latest_by_kind.values())
    age_by_kind = {
        kind: max(0.0, (now.timestamp() - path.stat().st_mtime) / 3600)
        for kind, path in latest_by_kind.items()
        if path is not None
    }
    age_hours = max(age_by_kind.values(), default=0.0)
    status = "OK"
    if age_hours > critical_hours:
        status = "CRITICAL"
    elif age_hours > warn_hours:
        status = "WARN"
    run_result = _load_latest_backup_run(latest_by_kind["backup_run"])
    restore_status = _restore_smoke_status(run_result)
    if restore_status == "failed":
        status = "CRITICAL"
    elif restore_status == "missing" and status == "OK":
        status = "WARN"
    _add_check(
        checks,
        name="backup_age",
        status=status,
        detail=f"primary backup set age_hours={age_hours:.1f} restore_smoke={restore_status}",
        data={
            "age_hours": round(age_hours, 1),
            "age_by_kind": {kind: round(age, 1) for kind, age in age_by_kind.items()},
            "paths": {kind: str(path) for kind, path in latest_by_kind.items() if path is not None},
            "restore_smoke": restore_status,
        },
    )


def _add_codex_login_check(
    checks: list[dict],
    *,
    log_path: Path,
    now: datetime,
    warn_minutes: int,
    critical_minutes: int,
) -> None:
    if not log_path.exists():
        _add_check(checks, name="codex_login_check", status="WARN", detail=f"login check log not found: {log_path}")
        return
    age_minutes = max(0.0, (now.timestamp() - log_path.stat().st_mtime) / 60)
    last_line = _last_non_empty_line(log_path)
    status = "OK"
    if "Logged in" not in last_line:
        status = "CRITICAL"
    elif age_minutes > critical_minutes:
        status = "CRITICAL"
    elif age_minutes > warn_minutes:
        status = "WARN"
    _add_check(
        checks,
        name="codex_login_check",
        status=status,
        detail=f"last_check_age_minutes={age_minutes:.1f}; last_status={last_line[:120]}",
        data={"age_minutes": round(age_minutes, 1)},
    )


def _check_url(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            status = getattr(response, "status", 200)
            body = response.read(256).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        return False, f"{url} failed: {type(exc).__name__}"
    if status >= 400:
        return False, f"{url} returned HTTP {status}"
    if '"status":"ok"' in body.replace(" ", "") or status < 400:
        return True, f"{url} returned HTTP {status}"
    return False, f"{url} returned unexpected body"


def _newest_matching_file(directory: Path, patterns: list[str]) -> Path | None:
    if not directory.exists():
        return None
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(path for path in directory.glob(pattern) if path.is_file())
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _load_latest_backup_run(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _restore_smoke_status(value: dict | None) -> str:
    if not value or "restore_smoke" not in value:
        return "missing"
    restore_smoke = value.get("restore_smoke")
    if _contains_ok_value(restore_smoke, False):
        return "failed"
    if _contains_ok_value(restore_smoke, True):
        return "ok"
    return "missing"


def _contains_ok_value(value, expected: bool) -> bool:
    if isinstance(value, dict):
        if value.get("ok") is expected:
            return True
        return any(_contains_ok_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_ok_value(item, expected) for item in value)
    return False


def _last_non_empty_line(path: Path) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        cleaned = line.strip()
        if cleaned:
            return cleaned
    return ""


def _add_check(
    checks: list[dict],
    *,
    name: str,
    status: str,
    detail: str,
    data: dict | None = None,
) -> None:
    check = {"name": name, "status": status, "detail": detail}
    if data:
        check["data"] = data
    checks.append(check)


def _overall_status(checks: list[dict]) -> str:
    score = max((STATUS_SCORE.get(check["status"], 0) for check in checks), default=0)
    for status, value in STATUS_SCORE.items():
        if value == score:
            return status
    return "OK"


def _aware(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
