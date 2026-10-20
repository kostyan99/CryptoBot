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

State = namedtuple("State", "settings next_report_at next_analytics_at next_facts_at")
Job = namedtuple("Job", "chat_id settings want_report want_analytics want_facts")

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
    # 2: отдельное расписание «интересных фактов»
    """
    ALTER TABLE users ADD COLUMN next_facts_at TIMESTAMPTZ;
    UPDATE users SET next_facts_at = date_trunc('hour', now()) + interval '1 hour';
    CREATE INDEX users_due_facts_idx
        ON users (next_facts_at)
        WHERE subscribed AND NOT blocked AND next_facts_at IS NOT NULL;
    """,
    # 3: антидубли алертов о резких движениях
    """
    CREATE TABLE move_alerts (
        chat_id BIGINT NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
        coin_id TEXT   NOT NULL,
        sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (chat_id, coin_id)
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


def _public(stored: dict, subscribed: bool) -> dict:
    s = S.merged(stored)
    s["enabled"] = bool(subscribed)
    return s


def ensure_user(chat_id: int, user=None, subscribe=None, touch: bool = True) -> State:
    """Создаёт пользователя при первом обращении (настройки по умолчанию, язык — английский).
    subscribe=True включает рассылку (команда /start)."""
    now = _now()
    username = getattr(user, "username", None)
    first_name = getattr(user, "first_name", None)
    nr0, na0, nf0 = S.compute_next(S.merged({}), now)

    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO users (chat_id, settings, next_report_at, next_analytics_at, next_facts_at)
            VALUES (%s, '{}'::jsonb, %s, %s, %s) ON CONFLICT (chat_id) DO NOTHING
            """,
            (chat_id, nr0, na0, nf0),
        )
        stored, subscribed, nr, na, nf = conn.execute(
            "SELECT settings, subscribed, next_report_at, next_analytics_at, next_facts_at "
            "FROM users WHERE chat_id = %s FOR UPDATE",
            (chat_id,),
        ).fetchone()
        s = S.merged(stored)
        if bool(subscribe) and not subscribed:
            subscribed = True
            nr, na, nf = S.compute_next(s, now)
        conn.execute(
            """
            UPDATE users SET
                username = COALESCE(%s, username),
                first_name = COALESCE(%s, first_name),
                blocked = FALSE,
                subscribed = %s,
                next_report_at = %s,
                next_analytics_at = %s,
                next_facts_at = %s,
                last_seen_at = now(),
                requests = requests + %s
            WHERE chat_id = %s
            """,
            (username, first_name, subscribed, nr, na, nf, 1 if touch else 0, chat_id),
        )
    return State(_public(stored, subscribed), nr, na, nf)


def get_state(chat_id: int):
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT settings, subscribed, next_report_at, next_analytics_at, next_facts_at "
            "FROM users WHERE chat_id = %s",
            (chat_id,),
        ).fetchone()
    if row is None:
        return None
    return State(_public(row[0], row[1]), row[2], row[3], row[4])


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
        nr, na, nf = S.compute_next(s, _now())
        conn.execute(
            "UPDATE users SET settings = %s, subscribed = %s, next_report_at = %s, "
            "next_analytics_at = %s, next_facts_at = %s, force_send = FALSE WHERE chat_id = %s",
            (Jsonb(s), subscribed, nr, na, nf, chat_id),
        )
    s["enabled"] = subscribed
    return State(s, nr, na, nf)


def set_subscribed(chat_id: int, value: bool) -> None:
    if get_state(chat_id) is not None:
        save_settings(chat_id, {"enabled": value})


def request_send_now(chat_id: int) -> bool:
    """Просит планировщик отправить всё сейчас (в обход тихих часов/дней)."""
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
    nr, na, nf = S.compute_next(S.merged({}), _now())
    with pool.connection() as conn:
        for chat_id in chat_ids:
            conn.execute(
                "INSERT INTO users (chat_id, settings, next_report_at, next_analytics_at, "
                "next_facts_at) VALUES (%s, '{}'::jsonb, %s, %s, %s) ON CONFLICT (chat_id) DO NOTHING",
                (chat_id, nr, na, nf),
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
                                    AND COALESCE((settings->>'analytics_enabled')::boolean, TRUE)),
                   count(*) FILTER (WHERE subscribed AND NOT blocked
                                    AND COALESCE((settings->>'facts_enabled')::boolean, TRUE))
            FROM users
            """
        ).fetchone()
        langs = conn.execute(
            "SELECT COALESCE(settings->>'lang', 'en'), count(*) FROM users "
            "WHERE subscribed AND NOT blocked GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    return {"total": row[0], "active": row[1], "blocked": row[2], "analytics": row[3],
            "facts": row[4], "langs": {k: v for k, v in langs}}


def active_currencies_langs() -> tuple:
    """(валюты активных пользователей, языки с аналитикой, языки с фактами) — для прогрева кэша."""
    with pool.connection() as conn:
        cur = conn.execute(
            "SELECT DISTINCT COALESCE(settings->>'currency', 'usd') "
            "FROM users WHERE subscribed AND NOT blocked"
        ).fetchall()
        ana = conn.execute(
            "SELECT DISTINCT COALESCE(settings->>'lang', 'en') FROM users "
            "WHERE subscribed AND NOT blocked "
            "AND COALESCE((settings->>'analytics_enabled')::boolean, TRUE)"
        ).fetchall()
        fact = conn.execute(
            "SELECT DISTINCT COALESCE(settings->>'lang', 'en') FROM users "
            "WHERE subscribed AND NOT blocked "
            "AND COALESCE((settings->>'facts_enabled')::boolean, TRUE)"
        ).fetchall()
    return [r[0] for r in cur], [r[0] for r in ana], [r[0] for r in fact]


def active_ids(after_id: int, limit: int = 1000) -> list:
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT chat_id FROM users WHERE subscribed AND NOT blocked "
            "AND chat_id > %s ORDER BY chat_id LIMIT %s",
            (after_id, limit),
        ).fetchall()
    return [r[0] for r in rows]


def claim_due(limit: int) -> tuple:
    """Атомарно забирает пачку пользователей, у которых наступил слот отчёта, аналитики и/или
    факта, сдвигает им расписание и возвращает задания на отправку.
    Возвращает (jobs, claimed_count, max_lag_seconds)."""
    now = _now()
    grace = config.LATE_GRACE_MIN * 60
    jobs, updates, max_lag, claimed = [], [], 0.0, 0
    with pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT chat_id, settings, next_report_at, next_analytics_at, next_facts_at, force_send
            FROM users
            WHERE subscribed AND NOT blocked
              AND (next_report_at <= %(now)s OR next_analytics_at <= %(now)s
                   OR next_facts_at <= %(now)s)
            ORDER BY LEAST(next_report_at, next_analytics_at, next_facts_at)
            LIMIT %(limit)s
            FOR UPDATE SKIP LOCKED
            """,
            {"now": now, "limit": limit},
        ).fetchall()
        for chat_id, stored, nr, na, nf, force in rows:
            claimed += 1
            s = S.merged(stored)

            def nxt(key):
                return S.next_slot(now, s["tz"], s[key], s["anchor_hour"])

            due_r = nr is not None and nr <= now
            due_a = s["analytics_enabled"] and na is not None and na <= now
            due_f = s["facts_enabled"] and nf is not None and nf <= now
            new_nr = nr
            new_na = (na if na is not None else nxt("analytics_interval")) if s["analytics_enabled"] else None
            new_nf = (nf if nf is not None else nxt("facts_interval")) if s["facts_enabled"] else None
            want_r, want_a, want_f = due_r, due_a, due_f

            if due_r:
                lag = (now - nr).total_seconds()
                max_lag = max(max_lag, lag)
                new_nr, want_r = nxt("report_interval"), lag <= grace
            if due_a:
                lag = (now - na).total_seconds()
                max_lag = max(max_lag, lag)
                new_na, want_a = nxt("analytics_interval"), lag <= grace
            if due_f:
                lag = (now - nf).total_seconds()
                max_lag = max(max_lag, lag)
                new_nf, want_f = nxt("facts_interval"), lag <= grace

            if force:
                want_r, want_a, want_f = True, s["analytics_enabled"], s["facts_enabled"]
            elif (want_r or want_a or want_f) and not S.is_allowed_now(s, now):
                want_r = want_a = want_f = False
            if want_a:
                want_f = False  # аналитика и факт не приходят вместе: в слот аналитики — только она

            if want_r or want_a or want_f:
                jobs.append(Job(chat_id, s, want_r, want_a, want_f))
            updates.append((new_nr, new_na, new_nf, chat_id))

        if updates:
            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE users SET next_report_at = %s, next_analytics_at = %s, "
                    "next_facts_at = %s, force_send = FALSE WHERE chat_id = %s",
                    updates,
                )
    return jobs, claimed, max_lag


def alert_users(after_id: int, limit: int = 500) -> list:
    """Пользователи с включёнными алертами о резких движениях: [(chat_id, settings)]."""
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT chat_id, settings FROM users WHERE subscribed AND NOT blocked "
            "AND COALESCE((settings->>'move_alerts')::boolean, TRUE) AND chat_id > %s "
            "ORDER BY chat_id LIMIT %s",
            (after_id, limit),
        ).fetchall()
    return [(r[0], S.merged(r[1])) for r in rows]


def recent_alerts(chat_ids: list, minutes: int) -> set:
    """{(chat_id, coin_id)}, по которым алерт уже отправляли в последние `minutes` минут."""
    if not chat_ids:
        return set()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT chat_id, coin_id FROM move_alerts WHERE chat_id = ANY(%s) "
            "AND sent_at > now() - make_interval(mins => %s)",
            (chat_ids, minutes),
        ).fetchall()
    return {(r[0], r[1]) for r in rows}


def mark_alerts(pairs: list) -> None:
    if not pairs:
        return
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO move_alerts (chat_id, coin_id) VALUES (%s, %s) "
                "ON CONFLICT (chat_id, coin_id) DO UPDATE SET sent_at = now()",
                pairs,
            )


def cleanup() -> None:
    with pool.connection() as conn:
        conn.execute("DELETE FROM move_alerts WHERE sent_at < now() - interval '2 days'")
