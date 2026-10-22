"""Спецификация настроек пользователя, валидация и расчёт расписания.
Единый источник правды для бота и веб-приложения."""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config

INTERVALS = [1, 2, 3, 4, 6, 8, 12, 24]
LANGS = ["en", "ru", "fr", "es", "de"]
CURRENCIES = ["usd", "eur", "rub", "uah", "kzt"]

SPEC = {
    "enabled": {"type": "bool"},
    "lang": {"type": "enum", "values": LANGS},
    "tz": {"type": "tz"},
    "report_interval": {"type": "enum", "values": INTERVALS},
    "analytics_enabled": {"type": "bool"},
    "analytics_interval": {"type": "enum", "values": [6, 12]},
    "facts_enabled": {"type": "bool"},
    "facts_interval": {"type": "enum", "values": INTERVALS},
    "anchor_hour": {"type": "int", "min": 0, "max": 23},
    "coins_count": {"type": "enum", "values": [3, 5, 10, 15, 20]},
    "currency": {"type": "enum", "values": CURRENCIES},
    "list_mode": {"type": "enum", "values": ["top", "gainers", "losers", "custom"]},
    "custom_coins": {"type": "coins", "max": 10},
    "show_indices": {"type": "bool"},
    "game_hide_name": {"type": "bool"},
    "weekly_enabled": {"type": "bool"},
    "weekly_day": {"type": "enum", "values": [0, 1, 2, 3, 4, 5, 6]},
    "move_alerts": {"type": "bool"},
    "move_threshold": {"type": "enum", "values": [3, 5, 7, 10, 15]},
    "change_period": {"type": "enum", "values": ["24h", "7d"]},
    "show_change": {"type": "bool"},
    "show_emoji": {"type": "bool"},
    "include_stables": {"type": "bool"},
    "quiet_enabled": {"type": "bool"},
    "quiet_start": {"type": "int", "min": 0, "max": 23},
    "quiet_end": {"type": "int", "min": 0, "max": 23},
    "days": {"type": "days"},
}

# "enabled" хранится отдельной колонкой subscribed, остальное — в JSONB
DEFAULTS = {
    "lang": "en",
    "tz": config.DEFAULT_TZ,
    "report_interval": 2,
    "analytics_enabled": True,
    "analytics_interval": 6,
    "facts_enabled": True,
    "facts_interval": 1,
    "anchor_hour": 0,
    "coins_count": 10,
    "currency": "usd",
    "list_mode": "top",
    "custom_coins": [],
    "show_indices": True,
    "game_hide_name": False,
    "weekly_enabled": True,
    "weekly_day": 6,
    "move_alerts": True,
    "move_threshold": 5,
    "change_period": "24h",
    "show_change": True,
    "show_emoji": True,
    "include_stables": False,
    "quiet_enabled": False,
    "quiet_start": 23,
    "quiet_end": 7,
    "days": [0, 1, 2, 3, 4, 5, 6],
}

TZ_CHOICES = [
    "Europe/Kyiv", "Europe/Warsaw", "Europe/Berlin", "Europe/Paris", "Europe/London",
    "Europe/Istanbul", "Europe/Moscow", "Europe/Minsk", "Asia/Tbilisi", "Asia/Yerevan",
    "Asia/Baku", "Asia/Dubai", "Asia/Tashkent", "Asia/Almaty", "Asia/Bangkok",
    "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney", "America/New_York",
    "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Sao_Paulo", "UTC",
]


def check_value(key: str, value):
    """Возвращает очищенное значение или бросает ValueError."""
    spec = SPEC.get(key)
    if spec is None:
        raise ValueError(f"unknown setting: {key}")
    t = spec["type"]
    if t == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{key}: expected boolean")
        return value
    if t == "enum":
        if isinstance(value, bool) or value not in spec["values"]:
            raise ValueError(f"{key}: invalid value")
        return value
    if t == "int":
        if isinstance(value, bool) or not isinstance(value, int) or not spec["min"] <= value <= spec["max"]:
            raise ValueError(f"{key}: out of range")
        return value
    if t == "tz":
        if not isinstance(value, str) or not value or len(value) > 64:
            raise ValueError("tz: invalid")
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError("tz: unknown timezone")
        return value
    if t == "coins":
        if (
            not isinstance(value, list)
            or len(value) > spec["max"]
            or len(set(map(str, value))) != len(value)
            or any(not isinstance(x, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", x) for x in value)
        ):
            raise ValueError("custom_coins: invalid list")
        return list(value)
    if t == "days":
        if (
            not isinstance(value, list)
            or not value
            or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in value)
        ):
            raise ValueError("days: invalid")
        return sorted(set(value))
    raise ValueError(f"{key}: unsupported type")


def validate_partial(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("body must be an object")
    return {k: check_value(k, v) for k, v in data.items()}


def merged(stored: dict) -> dict:
    """Дефолты + сохранённые значения (невалидные/устаревшие ключи игнорируются)."""
    result = dict(DEFAULTS)
    for key in DEFAULTS:
        if stored and key in stored:
            try:
                result[key] = check_value(key, stored[key])
            except ValueError:
                pass
    result["days"] = list(result["days"])
    result["custom_coins"] = list(result["custom_coins"])
    return result


def validate_consistency(s: dict) -> None:
    if s["list_mode"] == "custom" and not s["custom_coins"]:
        raise ValueError("choose at least one coin for 'My coins' mode")
    if s["quiet_enabled"] and s["quiet_start"] == s["quiet_end"]:
        raise ValueError("quiet hours: start and end must differ")


def next_slot(after: datetime, tz_name: str, interval: int, anchor: int) -> datetime:
    """Ближайший слот СТРОГО после `after`: локальное время tz, минута :00,
    час h такой, что (h - anchor) % interval == 0. Возвращает UTC."""
    tz = ZoneInfo(tz_name)
    t = after.astimezone(tz).replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    t += timedelta(hours=1)
    for _ in range(24 * 3):
        if (t.astimezone(tz).hour - anchor) % interval == 0:
            return t
        t += timedelta(hours=1)
    return t


def compute_next(s: dict, after: datetime) -> tuple:
    nr = next_slot(after, s["tz"], s["report_interval"], s["anchor_hour"])
    na = (
        next_slot(after, s["tz"], s["analytics_interval"], s["anchor_hour"])
        if s["analytics_enabled"]
        else None
    )
    nf = (
        next_slot(after, s["tz"], s["facts_interval"], s["anchor_hour"])
        if s["facts_enabled"]
        else None
    )
    return nr, na, nf


def is_allowed_now(s: dict, now_utc: datetime) -> bool:
    """Дни недели и тихие часы (по локальному времени пользователя)."""
    local = now_utc.astimezone(ZoneInfo(s["tz"]))
    if local.weekday() not in s["days"]:
        return False
    if s["quiet_enabled"]:
        h, a, b = local.hour, s["quiet_start"], s["quiet_end"]
        quiet = (a <= h < b) if a < b else (h >= a or h < b)
        if quiet:
            return False
    return True


def next_weekly(after: datetime, tz_name: str, weekday: int, hour: int) -> datetime:
    """Ближайший момент строго после `after`: локальный день недели `weekday` (пн=0), `hour`:00."""
    tz = ZoneInfo(tz_name)
    t = after.astimezone(tz).replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    t += timedelta(hours=1)
    for _ in range(24 * 8):
        local = t.astimezone(tz)
        if local.weekday() == weekday and local.hour == hour:
            return t
        t += timedelta(hours=1)
    return t


# Стартовые профили: один тап настраивает всё расписание и содержимое.
# Язык, часовой пояс и «свои монеты» профиль не трогает.
PROFILES = {
    "beginner": {
        "enabled": True, "report_interval": 4, "anchor_hour": 0,
        "analytics_enabled": True, "analytics_interval": 12,
        "facts_enabled": True, "facts_interval": 3,
        "list_mode": "top", "coins_count": 10, "show_change": True, "show_emoji": True,
        "show_indices": True, "move_alerts": True, "move_threshold": 10,
        "quiet_enabled": True, "quiet_start": 23, "quiet_end": 8, "weekly_enabled": True,
    },
    "trader": {
        "enabled": True, "report_interval": 1, "anchor_hour": 0,
        "analytics_enabled": True, "analytics_interval": 6, "facts_enabled": False,
        "list_mode": "top", "coins_count": 15, "change_period": "24h", "show_change": True,
        "show_indices": True, "move_alerts": True, "move_threshold": 3,
        "quiet_enabled": False, "weekly_enabled": True,
    },
    "minimal": {
        "enabled": True, "report_interval": 24, "anchor_hour": 9,
        "analytics_enabled": False, "facts_enabled": False,
        "list_mode": "top", "coins_count": 5, "show_indices": False,
        "move_alerts": True, "move_threshold": 10,
        "quiet_enabled": True, "quiet_start": 23, "quiet_end": 8, "weekly_enabled": True,
    },
    "explorer": {
        "enabled": True, "report_interval": 8, "anchor_hour": 0,
        "analytics_enabled": True, "analytics_interval": 12,
        "facts_enabled": True, "facts_interval": 1,
        "list_mode": "top", "coins_count": 5, "show_indices": True, "move_alerts": False,
        "quiet_enabled": True, "quiet_start": 23, "quiet_end": 8, "weekly_enabled": True,
    },
}
