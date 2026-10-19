"""PostgreSQL: схема (миграции), пользователи, настройки, очередь отправки."""
import logging
from collections import namedtuple
from datetime import datetime, timezone

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

import config
import settings as S

logger = logging.getLogger("db")
pool = ConnectionPool(
    config.DATABASE_URL, min_size=1, max_size=config.DB_POOL_MAX, open=False, timeout=15
)

State = namedtuple("State", "settings next_report_at next_analytics_at")
Job = namedtuple("Job", "chat_id settings want_report want_analytics")

MIGRATIONS = [
    """
    CREATE TABLE users (
        chat_id           BIGINT PRIMARY KEY,
        username          TEXT,
        first_name        TEXT,
        subscribed        BOOLEAN     NOT NULL DEFAULT TRUE,
        blocked           BOOLEAN     NOT NULL DEFAULT FALSE,
        settings          JSONB       NOT NULL DEFAULT '{}'::jsonb,
        next_report_at    TIMESTAMPTZ,
        next_analytics_at TIMESTAMPTZ,
        force_send        BOOLEAN     NOT NULL DEFAULT FALSE,
        created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        requests          INTEGER     NOT NULL DEFAULT 0
    );
    CREATE INDEX users_due_report_idx
        ON users (next_report_at) WHERE subscribed AND NOT blocked;
    CREATE INDEX users_due_analytics_idx
        ON users (next_analytics_at)
        WHERE subscribed AND NOT blocked AND next_analytics_at IS NOT NULL;
    CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def init_db() -> None:
    """Открывает пул и применяет миграции (под advisory-lock: бот и веб могут стартовать вместе)."""
    pool.open(wait=True, timeout=30)
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(727001)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        current = conn.execute("SELECT COALESCE(max(version), 0) FROM schema_version").fetchone()[0]
        for number, sql in enumerate(MIGRATIONS, start=1):
            if number > current:
                logger.info("Applying migration %s", number)
                conn.execute(sql)
                conn.execute("INSERT INTO schema_version (version) VALUES (%s)", (number,))


def guess_lang(code) -> str:
    if not code or code.lower().startswith(("ru", "uk", "be")):
        return "ru"
    return "en"


def _public(stored: dict, subscribed: bool) -> dict:
    s = S.merged(stored)
    s["enabled"] = bool(subscribed)
    return s


def ensure_user(chat_id: int, user=None, subscribe=None, touch: bool = True) -> State:
    """Создаёт пользователя при первом обращении (настройки по умолчанию).
    subscribe=True включает рассылку (команда /start)."""
    now = _now()
    lang = guess_lang(getattr(user, "language_code", None))
    username = getattr(user, "username", None)
    first_name = getattr(user, "first_name", None)
    init = S.merged({"lang": lang})
    nr0, na0 = S.compute_next(init, now)

    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO users (chat_id, settings, next_report_at, next_analytics_at)
            VALUES (%s, %s, %s, %s) ON CONFLICT (chat_id) DO NOTHING
            """,
            (chat_id, Jsonb({"lang": lang}), nr0, na0),
        )
        stored, subscribed, nr, na = conn.execute(
            "SELECT settings, subscribed, next_report_at, next_analytics_at "
            "FROM users WHERE chat_id = %s FOR UPDATE",
            (chat_id,),
        ).fetchone()
        s = S.merged(stored)
        resubscribe = bool(subscribe) and not subscribed
        if resubscribe:
            subscribed = True
            nr, na = S.compute_next(s, now)
        conn.execute(
            """
            UPDATE users SET
                username = COALESCE(%s, username),
                first_name = COALESCE(%s, first_name),
                blocked = FALSE,
                subscribed = %s,
                next_report_at = %s,
                next_analytics_at = %s,
                last_seen_at = now(),
                requests = requests + %s
            WHERE chat_id = %s
            """,
            (username, first_name, subscribed, nr, na, 1 if touch else 0, chat_id),
        )
    return State(_public(stored, subscribed), nr, na)


def get_state(chat_id: int):
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT settings, subscribed, next_report_at, next_analytics_at "
            "FROM users WHERE chat_id = %s",
            (chat_id,),
        ).fetchone()
    if row is None:
        return None
    return State(_public(row[0], row[1]), row[2], row[3])


def save_settings(chat_id: int, partial: dict) -> State:
    """Валидирует и сохраняет настройки, пересчитывает расписание.
    ValueError — некорректные данные, KeyError — пользователя нет."""
    clean = S.validate_partial(partial)
    enabled_new = clean.pop("enabled", None)
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT settings, subscribed FROM users WHERE chat_id = %s FOR UPDATE", (chat_id,)
        ).fetchone()
        if row is None:
            raise KeyError(chat_id)
        s = S.merged(row[0])
        s.update(clean)
        S.validate_consistency(s)
        subscribed = row[1] if enabled_new is None else enabled_new
        nr, na = S.compute_next(s, _now())
        conn.execute(
            "UPDATE users SET settings = %s, subscribed = %s, next_report_at = %s, "
            "next_analytics_at = %s, force_send = FALSE WHERE chat_id = %s",
            (Jsonb(s), subscribed, nr, na, chat_id),
        )
    s["enabled"] = subscribed
    return State(s, nr, na)


def set_subscribed(chat_id: int, value: bool) -> None:
    state = get_state(chat_id)
    if state is None:
        return
    save_settings(chat_id, {"enabled": value})


def request_send_now(chat_id: int) -> bool:
    """Просит планировщик отправить отчёт сейчас (в обход тихих часов/дней)."""
    with pool.connection() as conn:
        cur = conn.execute(
            "UPDATE users SET next_report_at = now(), force_send = TRUE "
            "WHERE chat_id = %s AND subscribed AND NOT blocked",
            (chat_id,),
        )
        return cur.rowcount > 0


def mark_blocked(chat_id: int) -> None:
    with pool.connection() as conn:
        conn.execute("UPDATE users SET blocked = TRUE WHERE chat_id = %s", (chat_id,))


def delete_user(chat_id: int) -> None:
    with pool.connection() as conn:
        conn.execute("DELETE FROM users WHERE chat_id = %s", (chat_id,))


def seed_users(chat_ids: list) -> None:
    now = _now()
    init = S.merged({})
    nr, na = S.compute_next(init, now)
    with pool.connection() as conn:
        for chat_id in chat_ids:
            conn.execute(
                "INSERT INTO users (chat_id, settings, next_report_at, next_analytics_at) "
                "VALUES (%s, '{}'::jsonb, %s, %s) ON CONFLICT (chat_id) DO NOTHING",
                (chat_id, nr, na),
            )


def get_meta(key: str):
    with pool.connection() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = %s", (key,)).fetchone()
    return row[0] if row else None


def set_meta(key: str, value: str) -> None:
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, value),
        )


def get_stats() -> dict:
    with pool.connection() as conn:
        row = conn.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE subscribed AND NOT blocked),
                   count(*) FILTER (WHERE blocked),
                   count(*) FILTER (WHERE subscribed AND NOT blocked
                                    AND COALESCE((settings->>'analytics_enabled')::boolean, TRUE))
            FROM users
            """
        ).fetchone()
    return {"total": row[0], "active": row[1], "blocked": row[2], "analytics": row[3]}


def active_currencies_langs() -> tuple:
    """(валюты активных пользователей, языки пользователей с аналитикой) — для прогрева кэша."""
    with pool.connection() as conn:
        cur = conn.execute(
            "SELECT DISTINCT COALESCE(settings->>'currency', 'usd') "
            "FROM users WHERE subscribed AND NOT blocked"
        ).fetchall()
        lng = conn.execute(
            "SELECT DISTINCT COALESCE(settings->>'lang', 'ru') FROM users "
            "WHERE subscribed AND NOT blocked "
            "AND COALESCE((settings->>'analytics_enabled')::boolean, TRUE)"
        ).fetchall()
    return [r[0] for r in cur], [r[0] for r in lng]


def active_ids(after_id: int, limit: int = 1000) -> list:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT chat_id FROM users WHERE subscribed AND NOT blocked "
            "AND chat_id > %s ORDER BY chat_id LIMIT %s",
            (after_id, limit),
        ).fetchall()
    return [r[0] for r in rows]


def claim_due(limit: int) -> tuple:
    """Атомарно забирает пачку пользователей, у которых наступил слот отчёта и/или аналитики,
    сдвигает им расписание и возвращает задания на отправку.
    Возвращает (jobs, claimed_count, max_lag_seconds)."""
    now = _now()
    grace = config.LATE_GRACE_MIN * 60
    jobs, updates, max_lag, claimed = [], [], 0.0, 0
    with pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT chat_id, settings, next_report_at, next_analytics_at, force_send
            FROM users
            WHERE subscribed AND NOT blocked
              AND (next_report_at <= %(now)s OR next_analytics_at <= %(now)s)
            ORDER BY LEAST(next_report_at, next_analytics_at)
            LIMIT %(limit)s
            FOR UPDATE SKIP LOCKED
            """,
            {"now": now, "limit": limit},
        ).fetchall()
        for chat_id, stored, nr, na, force in rows:
            claimed += 1
            s = S.merged(stored)
            report_due = nr is not None and nr <= now
            ana_due = s["analytics_enabled"] and na is not None and na <= now
            want_r, want_a = report_due, ana_due
            new_nr, new_na = nr, (na if s["analytics_enabled"] else None)

            if report_due:
                lag = (now - nr).total_seconds()
                max_lag = max(max_lag, lag)
                new_nr = S.next_slot(now, s["tz"], s["report_interval"], s["anchor_hour"])
                want_r = lag <= grace
            if ana_due:
                lag = (now - na).total_seconds()
                max_lag = max(max_lag, lag)
                new_na = S.next_slot(now, s["tz"], s["analytics_interval"], s["anchor_hour"])
                want_a = lag <= grace

            if force:
                want_r, want_a = True, s["analytics_enabled"]
            elif (want_r or want_a) and not S.is_allowed_now(s, now):
                want_r = want_a = False

            if want_r or want_a:
                jobs.append(Job(chat_id, s, want_r, want_a))
            updates.append((new_nr, new_na, chat_id))

        if updates:
            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE users SET next_report_at = %s, next_analytics_at = %s, "
                    "force_send = FALSE WHERE chat_id = %s",
                    updates,
                )
    return jobs, claimed, max_lag
