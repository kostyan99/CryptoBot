"""Веб-сервис мини-приложения «Настройки» (Telegram Web App): API + статика."""
import collections
import hashlib
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qsl

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

import config
import db
import settings as S

config.setup_logging("web")
logger = logging.getLogger("web")

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp", "index.html")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
    ),
}


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield
    db.pool.close()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def add_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def validate_init_data(init_data: str) -> dict:
    """Проверка подписи Telegram Web App initData (HMAC-SHA256 по токену бота)."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise ValueError("no hash")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", config.TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        raise ValueError("bad signature")
    if time.time() - int(pairs.get("auth_date", "0")) > config.WEB_AUTH_MAX_AGE:
        raise ValueError("initData expired")
    user = json.loads(pairs["user"])
    if not isinstance(user.get("id"), int):
        raise ValueError("no user")
    return user


def current_user(request: Request) -> dict:
    try:
        return validate_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    except Exception:
        raise HTTPException(status_code=401, detail="unauthorized")


_hits: dict = collections.defaultdict(collections.deque)


def rate_limit(uid: int, name: str, limit: int, per: int) -> None:
    q, now = _hits[(uid, name)], time.time()
    while q and now - q[0] > per:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail="too many requests")
    q.append(now)
    if len(_hits) > 5000:
        for key in [k for k, v in _hits.items() if not v or now - v[-1] > per]:
            _hits.pop(key, None)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def payload(state) -> dict:
    return {
        "settings": state.settings,
        "next_report_at": _iso(state.next_report_at),
        "next_analytics_at": _iso(state.next_analytics_at),
        "next_facts_at": _iso(state.next_facts_at),
    }


def top_coins() -> list:
    """Список топ-100 монет для выбора (его пишет бот в таблицу meta)."""
    try:
        raw = db.get_meta("top_coins")
        return json.loads(raw) if raw else []
    except Exception:
        return []


@app.get("/")
def index():
    return FileResponse(INDEX, media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/api/settings")
def get_settings(request: Request):
    user = current_user(request)
    rate_limit(user["id"], "get", 60, 60)
    state = db.get_state(user["id"])
    if state is None:  # пользователь удалён или ещё не нажимал /start
        raise HTTPException(status_code=404, detail="no_user")
    return {**payload(state), "spec": S.SPEC, "tz_choices": S.TZ_CHOICES, "coins": top_coins(),
            "profiles": S.PROFILES}


@app.put("/api/settings")
def put_settings(request: Request, data: dict = Body(...)):
    user = current_user(request)
    rate_limit(user["id"], "put", 30, 60)
    picked = data.get("custom_coins")
    if isinstance(picked, list):
        known = {c["id"] for c in top_coins()}
        if known and any(x not in known for x in picked):
            raise HTTPException(status_code=400, detail="custom_coins: coin is not in the top 100")
    try:
        state = db.save_settings(user["id"], data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="user not found")
    return payload(state)


@app.post("/api/send_now")
def send_now(request: Request):
    user = current_user(request)
    rate_limit(user["id"], "send", 3, 60)
    if not db.request_send_now(user["id"]):
        raise HTTPException(status_code=409, detail="reports are disabled")
    return {"ok": True}


@app.delete("/api/me")
def delete_me(request: Request):
    """Удаляет все данные пользователя (настройки, прогресс игры, просмотренные факты)."""
    user = current_user(request)
    rate_limit(user["id"], "delete", 3, 60)
    db.delete_user(user["id"])
    return {"ok": True}


@app.get("/healthz")
def healthz():
    try:
        beat = db.get_meta("bot_heartbeat")
    except Exception:
        return JSONResponse({"ok": False, "db": False}, status_code=503)
    age = None
    if beat:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(beat)).total_seconds()
    ok = age is not None and age < 180
    return JSONResponse({"ok": ok, "db": True, "bot_heartbeat_age": age},
                        status_code=200 if ok else 503)
