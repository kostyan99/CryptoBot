"""Конфигурация из переменных окружения (.env) и настройка логирования."""
import logging
import os
import re
import sys


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _ids(name: str) -> list:
    raw = os.getenv(name, "").strip()
    return [int(x) for x in re.split(r"[,\s]+", raw) if x]


TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"]) if os.getenv("ADMIN_CHAT_ID") else None
USER_CHAT_IDS = _ids("USER_CHAT_ID")  # стартовые пользователи (добавляются в БД при запуске)
WEBAPP_URL = (os.getenv("WEBAPP_URL") or "").rstrip("/")  # https://bot.example.com
# Один или несколько ключей Gemini через запятую: GEMINI_API_KEYS=key1,key2
GEMINI_KEYS = [
    k.strip()
    for k in (os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or "").split(",")
    if k.strip()
]
GEMINI_MODELS = [
    m.strip()
    for m in os.getenv(
        "GEMINI_MODELS", "gemini-3.5-flash,gemini-3.1-flash-lite,gemini-2.5-flash"
    ).split(",")
    if m.strip()
]
COINGECKO_KEY = os.getenv("COINGECKO_API_KEY")

DEFAULT_TZ = os.getenv("DEFAULT_TZ", "Europe/Kyiv")  # для новых пользователей и дайджеста админа
CACHE_TTL = _int("CACHE_TTL", 120)  # сек: кэш курсов CoinGecko
STALE_MAX_SEC = _int("STALE_MAX_SEC", 3600)  # старше этого кэш не отдаём
AI_CACHE_MIN = _int("AI_CACHE_MIN", 50)  # минут: аналитика считается свежей
AI_STALE_HOURS = _int("AI_STALE_HOURS", 6)  # до скольки часов можно отдавать прошлую аналитику при сбоях
LATE_GRACE_MIN = _int("LATE_GRACE_MIN", 45)  # опоздавшие дольше этого слоты пропускаются
DISPATCH_BATCH = _int("DISPATCH_BATCH", 500)
BROADCAST_RPS = _float("BROADCAST_RPS", 25)  # лимит Telegram ~30 сообщений/сек
BROADCAST_WORKERS = _int("BROADCAST_WORKERS", 8)
BOT_THREADS = _int("BOT_THREADS", 16)
DB_POOL_MAX = _int("DB_POOL_MAX", 20)
WEB_AUTH_MAX_AGE = _int("WEB_AUTH_MAX_AGE", 86400)  # возраст initData мини-приложения
MOVE_CHECK_MIN = _int("MOVE_CHECK_MIN", 10)  # как часто проверять резкие движения, минуты
ALERT_COOLDOWN_MIN = _int("ALERT_COOLDOWN_MIN", 180)  # повторный алерт по той же монете не раньше
INDICES_TTL = _int("INDICES_TTL", 600)  # кэш Fear & Greed и доминирования BTC, секунды
DIGEST_HOUR = _int("DIGEST_HOUR", 9)  # час ежедневного дайджеста админу (DEFAULT_TZ)


def check_required() -> None:
    missing = [n for n, v in (("BOT_TOKEN", TOKEN), ("DATABASE_URL", DATABASE_URL)) if not v]
    if missing:
        print(f"Missing required env: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)


def setup_logging(service: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s %(levelname)s [{service}] %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpcore", "urllib3", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    import alerts  # локальный импорт: alerts зависит от config

    alerts.install(service)
    if not ADMIN_CHAT_ID:
        logging.getLogger("config").warning("ADMIN_CHAT_ID not set: admin alerts disabled")


check_required()
