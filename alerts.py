"""Алерты админу в Telegram: ошибки (logging ERROR+) и ручные уведомления.
Дедупликация + лимит, чтобы авария не превратилась в спам."""
import collections
import html
import logging
import queue
import threading
import time
import traceback

import requests

import config

log = logging.getLogger("alerts")
_q: "queue.Queue[str]" = queue.Queue(maxsize=100)
_last: dict = {}
_window: collections.deque = collections.deque()
_lock = threading.Lock()
_service = "app"
_started = False
MAX_PER_HOUR = 30


def _sanitize(text: str) -> str:
    return text.replace(config.TOKEN, "***") if config.TOKEN else text


def notify(text: str, key: str = None, cooldown: int = 600) -> None:
    if not config.ADMIN_CHAT_ID:
        return
    k = key or text[:120]
    now = time.time()
    with _lock:
        if now - _last.get(k, 0) < cooldown:
            return
        while _window and now - _window[0] > 3600:
            _window.popleft()
        if len(_window) >= MAX_PER_HOUR:
            return
        _window.append(now)
        _last[k] = now
        if len(_last) > 500:
            for old in [x for x, ts in _last.items() if now - ts > 3600]:
                _last.pop(old, None)
    try:
        _q.put_nowait(f"[{_service}] {text}")
    except queue.Full:
        pass


def _worker() -> None:
    while True:
        text = _q.get()
        try:
            requests.post(
                f"https://api.telegram.org/bot{config.TOKEN}/sendMessage",
                json={
                    "chat_id": config.ADMIN_CHAT_ID,
                    "text": _sanitize(text)[:4000],
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
        except Exception as e:
            log.warning("alert delivery failed: %s", _sanitize(str(e)))


def flush(timeout: float = 5.0) -> None:
    end = time.time() + timeout
    while not _q.empty() and time.time() < end:
        time.sleep(0.1)
    time.sleep(0.5)


class AdminLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("alerts") or record.levelno < logging.ERROR:
            return
        try:
            msg = _sanitize(record.getMessage())[:1200]
            
            # Фильтр для игнорирования штатных сетевых таймаутов от telebot
            if "Read timed out" in msg or "Connection reset by peer" in msg:
                return
                
            exc = ""
            if record.exc_info:
                exc = "\n" + _sanitize("".join(traceback.format_exception(*record.exc_info)[-2:]))[:1200]
            text = (
                f"🚨 <b>{record.levelname}</b> <code>{html.escape(record.name)}</code>\n"
                f"<pre>{html.escape(msg + exc)}</pre>"
            )
            notify(text, key=f"{record.name}:{msg[:100]}")
        except Exception:
            pass


def install(service: str) -> None:
    global _service, _started
    _service = service
    if _started:
        return
    _started = True
    threading.Thread(target=_worker, daemon=True, name="alerts").start()
    logging.getLogger().addHandler(AdminLogHandler(level=logging.ERROR))
