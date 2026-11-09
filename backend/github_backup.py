"""
Резервное копирование состояния расписания в GitHub-репозиторий
(через GitHub Contents API).

Нужно на бесплатных хостингах (Hugging Face Spaces, Render free и т.п.),
где файловая система эфемерна: после каждой загрузки файла админом
state.json автоматически коммитится в репозиторий, а при старте сервера
с пустым локальным хранилищем — восстанавливается оттуда.

Настройка через переменные окружения (в HF — через Secrets):
  BACKUP_GH_TOKEN   personal access token с правом contents: write (или fine-grained)
  BACKUP_GH_REPO    «владелец/репозиторий», напр. allexme8-create/new-raspisanie
  BACKUP_GH_BRANCH  ветка для бэкапа (по умолчанию "schedule-data", создаётся автоматически)
  BACKUP_GH_PATH    путь файла в репозитории (по умолчанию "backup/state.json")
"""
from __future__ import annotations

import base64
import os
import sys
import threading
import time

import requests

TOKEN = os.environ.get("BACKUP_GH_TOKEN", "").strip()
REPO = os.environ.get("BACKUP_GH_REPO", "").strip()
BRANCH = os.environ.get("BACKUP_GH_BRANCH", "schedule-data").strip() or "schedule-data"
PATH = os.environ.get("BACKUP_GH_PATH", "backup/state.json").strip() or "backup/state.json"

API = "https://api.github.com"
TIMEOUT = 30


def enabled() -> bool:
    return bool(TOKEN and REPO)


def _log(msg: str) -> None:
    print(f"[github-backup] {msg}", file=sys.stderr, flush=True)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _ensure_branch() -> bool:
    """Убедиться, что ветка бэкапа существует (создать от default-ветки)."""
    try:
        ref = requests.get(
            f"{API}/repos/{REPO}/git/ref/heads/{BRANCH}",
            headers=_headers(), timeout=TIMEOUT,
        )
        if ref.ok:
            return True
        if ref.status_code != 404:
            _log(f"не удалось проверить ветку {BRANCH}: HTTP {ref.status_code}")
            return False
        repo = requests.get(f"{API}/repos/{REPO}", headers=_headers(), timeout=TIMEOUT)
        repo.raise_for_status()
        default_branch = repo.json().get("default_branch", "main")
        head = requests.get(
            f"{API}/repos/{REPO}/git/ref/heads/{default_branch}",
            headers=_headers(), timeout=TIMEOUT,
        )
        head.raise_for_status()
        sha = head.json()["object"]["sha"]
        created = requests.post(
            f"{API}/repos/{REPO}/git/refs",
            headers=_headers(), timeout=TIMEOUT,
            json={"ref": f"refs/heads/{BRANCH}", "sha": sha},
        )
        if created.ok:
            _log(f"создана ветка {BRANCH}")
            return True
        _log(f"не удалось создать ветку {BRANCH}: HTTP {created.status_code}")
        return False
    except Exception as exc:  # noqa: BLE001
        _log(f"ensure_branch: {exc}")
        return False


def restore_state() -> bytes | None:
    """Скачать state.json из репозитория; None, если не найден/выключено."""
    if not enabled():
        return None
    try:
        resp = requests.get(
            f"{API}/repos/{REPO}/contents/{PATH}",
            params={"ref": BRANCH},
            headers=_headers(), timeout=TIMEOUT,
        )
        if resp.status_code == 404:
            _log(f"в репозитории нет {PATH} ({BRANCH}) — восстанавливать нечего")
            return None
        resp.raise_for_status()
        data = resp.json()
        content = base64.b64decode(data["content"])
        _log(f"восстановлено состояние из GitHub ({len(content)} байт)")
        return content
    except Exception as exc:  # noqa: BLE001
        _log(f"restore: {exc}")
        return None


def backup_state(content: str) -> bool:
    """Закоммитить state.json в репозиторий (с ретраями при конфликте sha)."""
    if not enabled():
        return False
    for attempt in range(3):
        try:
            if not _ensure_branch():
                return False
            url = f"{API}/repos/{REPO}/contents/{PATH}"
            sha = None
            cur = requests.get(url, params={"ref": BRANCH}, headers=_headers(), timeout=TIMEOUT)
            if cur.ok:
                sha = cur.json().get("sha")
            body = {
                "message": "Обновление расписания (автобэкап)",
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": BRANCH,
            }
            if sha:
                body["sha"] = sha
            resp = requests.put(url, headers=_headers(), json=body, timeout=TIMEOUT)
            if resp.ok:
                _log(f"бэкап сохранён: {PATH} @ {BRANCH}")
                return True
            if resp.status_code == 409 and attempt < 2:  # sha успел измениться — пробуем заново
                _log(f"backup: конфликт 409, повтор {attempt + 2}/3")
                time.sleep(1)
                continue
            _log(f"backup: HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        except Exception as exc:  # noqa: BLE001
            _log(f"backup: {exc}")
            return False
    return False


# ── Планировщик: «схлопывает» серию сохранений в один коммит ──────────────
_pending_lock = threading.Lock()
_pending_content: str | None = None
_pending_thread: threading.Thread | None = None
_DEBOUNCE_SEC = 3


def schedule_backup(content: str) -> None:
    """Запланировать бэкап: если сохранения идут подряд — закоммитится последнее."""
    global _pending_content, _pending_thread
    if not enabled():
        return
    with _pending_lock:
        _pending_content = content
        if _pending_thread and _pending_thread.is_alive():
            return
        _pending_thread = threading.Thread(target=_backup_worker, daemon=True)
        _pending_thread.start()


def _backup_worker() -> None:
    global _pending_content, _pending_thread
    time.sleep(_DEBOUNCE_SEC)
    while True:
        with _pending_lock:
            content = _pending_content
            _pending_content = None
        if content is None:
            return
        backup_state(content)


def flush_backup() -> None:
    """Дождаться завершения запланированного бэкапа (для тестов/остановки)."""
    t = _pending_thread
    if t and t.is_alive():
        t.join(timeout=TIMEOUT * 4)


def backup_status() -> dict:
    """Для /api/admin/status — видно, настроен ли бэкап."""
    return {"enabled": enabled(), "repo": REPO or None, "branch": BRANCH, "path": PATH}
