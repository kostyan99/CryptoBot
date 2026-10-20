"""Telegram-бот: команды, персональное расписание рассылки, админ-инструменты."""
import collections
import html
import json
import logging
import re
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

import alerts
import config
import db
import market as M
import settings as S

config.setup_logging("bot")
logger = logging.getLogger("bot")

bot = telebot.TeleBot(config.TOKEN, threaded=True, num_threads=config.BOT_THREADS)
stop = threading.Event()
started_at = time.time()

counters = collections.Counter()
counters_lock = threading.Lock()
pending_broadcast: dict = {}


def count(name: str, n: int = 1) -> None:
    with counters_lock:
        counters[name] += n


# ------------------------------------------------------------------
# Тексты
# ------------------------------------------------------------------
T = {
    "en": {
        "start": "👋 <b>Hi!</b> I send top-coin prices, AI analytics and fun crypto facts.\n\n{summary}\n\n"
                 "Everything is configurable via the “⚙️ Settings” button.",
        "rep": "📬 Prices", "ana": "🧠 Analytics", "fact": "💡 Facts", "al": "🚨 Alerts",
        "every": "every {n} h", "off": "off", "reports_off": "🔕 Reports are off",
        "stop": "🔕 Reports are off. Turn on: /start or “⚙️ Settings”.",
        "settings": "Open the bot settings:",
        "no_webapp": "⚠️ Settings are temporarily unavailable.",
        "btn_settings": "⚙️ Settings", "btn_top": "📊 Prices now",
        "err": "⚠️ Could not fetch data. Please try again in a minute.",
        "help": "📖 <b>Commands</b>\n/top — prices now\n/settings — settings\n/stop — stop reports\n"
                "/start — enable reports\n/delete — delete my data",
        "delete_hint": "To delete all your data, send: /delete confirm",
        "deleted": "🗑 Your data has been deleted. Send /start to come back.",
    },
    "ru": {
        "start": "👋 <b>Привет!</b> Я присылаю курс топ-монет, AI-аналитику и интересные факты о крипте.\n\n"
                 "{summary}\n\nВсё настраивается кнопкой «⚙️ Настройки».",
        "rep": "📬 Курс", "ana": "🧠 Аналитика", "fact": "💡 Факты", "al": "🚨 Алерты",
        "every": "каждые {n} ч", "off": "выключено", "reports_off": "🔕 Рассылка выключена",
        "stop": "🔕 Рассылка отключена. Вернуть: /start или «⚙️ Настройки».",
        "settings": "Откройте настройки бота:",
        "no_webapp": "⚠️ Настройки временно недоступны.",
        "btn_settings": "⚙️ Настройки", "btn_top": "📊 Курс сейчас",
        "err": "⚠️ Не удалось получить данные. Попробуйте через минуту.",
        "help": "📖 <b>Команды</b>\n/top — курс сейчас\n/settings — настройки\n/stop — отключить рассылку\n"
                "/start — включить рассылку\n/delete — удалить мои данные",
        "delete_hint": "Чтобы удалить все ваши данные, отправьте: /delete confirm",
        "deleted": "🗑 Ваши данные удалены. Чтобы вернуться, отправьте /start.",
    },
    "fr": {
        "start": "👋 <b>Salut !</b> J’envoie les cours des principales cryptos, des analyses IA et des "
                 "anecdotes crypto.\n\n{summary}\n\nTout se règle via le bouton « ⚙️ Paramètres ».",
        "rep": "📬 Cours", "ana": "🧠 Analyse", "fact": "💡 Anecdotes", "al": "🚨 Alertes",
        "every": "toutes les {n} h", "off": "désactivé", "reports_off": "🔕 Envois désactivés",
        "stop": "🔕 Envois désactivés. Pour réactiver : /start ou « ⚙️ Paramètres ».",
        "settings": "Ouvrez les paramètres du bot :",
        "no_webapp": "⚠️ Paramètres temporairement indisponibles.",
        "btn_settings": "⚙️ Paramètres", "btn_top": "📊 Cours maintenant",
        "err": "⚠️ Impossible de récupérer les données. Réessayez dans une minute.",
        "help": "📖 <b>Commandes</b>\n/top — cours maintenant\n/settings — paramètres\n"
                "/stop — arrêter les envois\n/start — activer les envois\n/delete — supprimer mes données",
        "delete_hint": "Pour supprimer toutes vos données, envoyez : /delete confirm",
        "deleted": "🗑 Vos données ont été supprimées. Envoyez /start pour revenir.",
    },
    "es": {
        "start": "👋 <b>¡Hola!</b> Envío precios de las principales criptomonedas, análisis con IA y "
                 "datos curiosos.\n\n{summary}\n\nTodo se configura con el botón «⚙️ Ajustes».",
        "rep": "📬 Precios", "ana": "🧠 Análisis", "fact": "💡 Datos curiosos", "al": "🚨 Alertas",
        "every": "cada {n} h", "off": "desactivado", "reports_off": "🔕 Envíos desactivados",
        "stop": "🔕 Envíos desactivados. Para volver: /start o «⚙️ Ajustes».",
        "settings": "Abre los ajustes del bot:",
        "no_webapp": "⚠️ Los ajustes no están disponibles temporalmente.",
        "btn_settings": "⚙️ Ajustes", "btn_top": "📊 Precios ahora",
        "err": "⚠️ No se pudieron obtener los datos. Inténtalo de nuevo en un minuto.",
        "help": "📖 <b>Comandos</b>\n/top — precios ahora\n/settings — ajustes\n/stop — detener envíos\n"
                "/start — activar envíos\n/delete — borrar mis datos",
        "delete_hint": "Para borrar todos tus datos, envía: /delete confirm",
        "deleted": "🗑 Tus datos han sido eliminados. Envía /start para volver.",
    },
    "de": {
        "start": "👋 <b>Hallo!</b> Ich sende Kurse der Top-Coins, KI-Analysen und spannende Krypto-Fakten."
                 "\n\n{summary}\n\nAlles lässt sich über die Schaltfläche „⚙️ Einstellungen“ anpassen.",
        "rep": "📬 Kurse", "ana": "🧠 Analyse", "fact": "💡 Fakten", "al": "🚨 Alarme",
        "every": "alle {n} Std.", "off": "aus", "reports_off": "🔕 Versand ist aus",
        "stop": "🔕 Versand ist aus. Wieder einschalten: /start oder „⚙️ Einstellungen“.",
        "settings": "Bot-Einstellungen öffnen:",
        "no_webapp": "⚠️ Einstellungen sind vorübergehend nicht verfügbar.",
        "btn_settings": "⚙️ Einstellungen", "btn_top": "📊 Kurse jetzt",
        "err": "⚠️ Daten konnten nicht abgerufen werden. Bitte in einer Minute erneut versuchen.",
        "help": "📖 <b>Befehle</b>\n/top — Kurse jetzt\n/settings — Einstellungen\n/stop — Versand stoppen\n"
                "/start — Versand aktivieren\n/delete — meine Daten löschen",
        "delete_hint": "Um alle Ihre Daten zu löschen, senden Sie: /delete confirm",
        "deleted": "🗑 Ihre Daten wurden gelöscht. Senden Sie /start, um zurückzukehren.",
    },
}

# описания команд в меню Telegram: top, settings, stop, start, help
COMMANDS = {
    "en": ["Prices now", "Settings", "Stop reports", "Start reports", "Help"],
    "ru": ["Курс сейчас", "Настройки", "Отключить рассылку", "Включить рассылку", "Помощь"],
    "fr": ["Cours maintenant", "Paramètres", "Arrêter les envois", "Activer les envois", "Aide"],
    "es": ["Precios ahora", "Ajustes", "Detener envíos", "Activar envíos", "Ayuda"],
    "de": ["Kurse jetzt", "Einstellungen", "Versand stoppen", "Versand aktivieren", "Hilfe"],
}


def summary(s: dict) -> str:
    t = T[s["lang"]]
    if not s["enabled"]:
        return t["reports_off"]

    def line(label, on, n):
        return f"{label}: " + (t["every"].format(n=n) if on else t["off"])

    return "\n".join([
        line(t["rep"], True, s["report_interval"]),
        line(t["ana"], s["analytics_enabled"], s["analytics_interval"]),
        line(t["fact"], s["facts_enabled"], s["facts_interval"]),
        f"{t['al']}: " + (f"≥{s['move_threshold']}%" if s["move_alerts"] else t["off"]),
    ])


# ------------------------------------------------------------------
# Клавиатуры
# ------------------------------------------------------------------
def settings_markup(lang: str):
    if not config.WEBAPP_URL:
        return None
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        T[lang]["btn_settings"], web_app=types.WebAppInfo(config.WEBAPP_URL)))
    return kb


def main_keyboard(lang: str):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(T[lang]["btn_top"], T[lang]["btn_settings"])
    return kb


# ------------------------------------------------------------------
# Отправка (лимиты Telegram, блокировки)
# ------------------------------------------------------------------
class RateLimiter:
    def __init__(self, rate: float):
        self.interval = 1.0 / rate
        self.lock = threading.Lock()
        self.next_time = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next_time)
            self.next_time = t + self.interval
        if t > now:
            time.sleep(t - now)


limiter = RateLimiter(config.BROADCAST_RPS)


def send(chat_id, text: str, throttle: bool = False, markup=None, silent: bool = False) -> str:
    """Возвращает 'ok' | 'blocked' | 'error'."""
    parse_mode = "HTML"
    for _ in range(4):
        if throttle:
            limiter.wait()
        try:
            bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=markup,
                             disable_notification=silent)
            return "ok"
        except ApiTelegramException as e:
            code, desc = e.error_code, (e.description or "").lower()
            if code == 429:
                retry = (e.result_json or {}).get("parameters", {}).get("retry_after", 5)
                logger.warning("Flood control: sleeping %ss", retry)
                time.sleep(int(retry) + 1)
                continue
            if code == 403 or (code == 400 and "chat not found" in desc):
                return "blocked"
            if code == 400 and "parse entities" in desc and parse_mode:
                parse_mode, text = None, re.sub(r"<[^>]+>", "", text)
                continue
            logger.warning("Telegram error for %s: %s", chat_id, e)
            return "error"
        except Exception as e:
            logger.warning("Send failed for %s: %s", chat_id, e)
            time.sleep(1)
    return "error"


def deliver(item: tuple) -> str:
    chat_id, text, lang, silent = item
    result = send(chat_id, text, throttle=True, markup=settings_markup(lang), silent=silent)
    if result == "blocked":
        try:
            db.mark_blocked(chat_id)
        except Exception:
            logger.exception("mark_blocked failed for %s", chat_id)
    count("sent_" + result)
    return result


# ------------------------------------------------------------------
# Диспетчер: персональное расписание
# ------------------------------------------------------------------
def dispatcher_loop() -> None:
    ex = ThreadPoolExecutor(max_workers=config.BROADCAST_WORKERS)
    while not stop.is_set():
        try:
            jobs, claimed, max_lag = db.claim_due(config.DISPATCH_BATCH)
        except Exception:
            logger.exception("Dispatcher: claim_due failed")
            stop.wait(5)
            continue

        if claimed == 0:
            stop.wait(1.0)
            continue

        if max_lag > 600:
            alerts.notify(
                f"⏱ Рассылка отстаёт на {max_lag / 60:.0f} мин. Увеличьте BROADCAST_RPS "
                f"или проверьте нагрузку.", key="lag", cooldown=1800)

        # курсы нужных валют — один раз на пачку
        failed = set()
        for cur in {j.settings["currency"] for j in jobs if j.want_report}:
            try:
                M.get_markets(cur)
            except Exception as e:
                failed.add(cur)
                logger.error("Market data unavailable (%s): %s", cur, e)

        items = []
        for job in jobs:
            s = job.settings
            want_r = job.want_report and s["currency"] not in failed
            if job.want_report and not want_r:
                count("skipped_no_data")
            try:
                text = M.compose(s, want_r, job.want_analytics, job.want_facts)
            except Exception:
                logger.exception("compose failed for %s", job.chat_id)
                continue
            if text:
                # сообщение только с фактом приходит без звука
                silent = not (want_r or job.want_analytics)
                items.append((job.chat_id, text, s["lang"], silent))

        if items:
            list(ex.map(deliver, items))
    ex.shutdown(wait=True)


# ------------------------------------------------------------------
# Прогрев кэша перед слотами, heartbeat, дайджест
# ------------------------------------------------------------------
def _sleep_until(target: datetime) -> bool:
    while not stop.is_set():
        remaining = (target - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return True
        stop.wait(min(remaining, 30))
    return False


def prepare(force_ai: bool) -> None:
    try:
        currencies, ana_langs, fact_langs = db.active_currencies_langs()
        for cur in sorted(set(currencies) | {"usd"}):
            try:
                data = M.get_markets(cur, max_age=0)
                if cur == "usd":  # список топ-100 для выбора «своих монет» в мини-приложении
                    db.set_meta("top_coins", json.dumps(M.top_coins_snapshot(data), ensure_ascii=False))
            except Exception as e:
                logger.error("Prepare: market data unavailable (%s): %s", cur, e)
            time.sleep(2)
        M.get_indices(max_age=0)
        # один запрос к Gemini на вид текста — сразу на всех языках
        if ana_langs:
            M.get_ai_text("analysis", ana_langs[0], force=force_ai)
        if fact_langs:
            M.get_ai_text("fact", fact_langs[0], force=force_ai)
    except Exception:
        logger.exception("Prepare step failed")


def prepare_loop() -> None:
    """Прогрев при старте, затем в :28 и :58 каждого часа: обновляет курсы, а в :58 — ещё и
    аналитику (раз в час, один запрос к Gemini на язык). Пользователям она отдаётся из кэша."""
    prepare(force_ai=False)
    while not stop.is_set():
        t = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
        while t.minute not in (28, 58):
            t += timedelta(minutes=1)
        if not _sleep_until(t):
            return
        prepare(force_ai=(t.minute == 58))


def check_moves() -> None:
    """Ищет резкие движения за 1 час и шлёт пользователям алерты по их монетам."""
    try:
        data = M.get_markets("usd", max_age=0)
    except Exception as e:
        logger.warning("Move check skipped, no market data: %s", e)
        return
    movers = M.find_movers(data, 3.0)  # 3% — минимальный порог из настроек
    if not movers:
        return
    now = datetime.now(timezone.utc)
    last_id, sent = 0, 0
    with ThreadPoolExecutor(max_workers=config.BROADCAST_WORKERS) as ex:
        while True:
            users = db.alert_users(last_id, 500)
            if not users:
                break
            last_id = users[-1][0]
            cooled = db.recent_alerts([u[0] for u in users], config.ALERT_COOLDOWN_MIN)
            items, marks = [], []
            for chat_id, s in users:
                if not S.is_allowed_now(s, now):
                    continue
                hits = []
                for coin_id in M.alert_scope(s, data):
                    m = movers.get(coin_id)
                    if m and abs(m[1]) >= s["move_threshold"] and (chat_id, coin_id) not in cooled:
                        hits.append((coin_id, m[0], m[1]))
                if not hits:
                    continue
                try:
                    price_data = M.get_markets(s["currency"])
                except Exception:
                    continue
                items.append((chat_id, M.build_alert_text(s, hits, price_data), s["lang"], False))
                marks.append([(chat_id, h[0]) for h in hits])
            if items:
                results = list(ex.map(deliver, items))
                db.mark_alerts([pair for res, pairs in zip(results, marks) if res == "ok" for pair in pairs])
                sent += sum(1 for r in results if r == "ok")
    if sent:
        count("alerts_sent", sent)
        logger.info("Move alerts sent: %s", sent)


def moves_loop() -> None:
    stop.wait(90)  # даём боту прогреться после старта
    while not stop.is_set():
        try:
            check_moves()
        except Exception:
            logger.exception("Move check failed")
        stop.wait(config.MOVE_CHECK_MIN * 60)


def heartbeat_loop() -> None:
    tz = ZoneInfo(config.DEFAULT_TZ)
    while not stop.is_set():
        try:
            db.set_meta("bot_heartbeat", datetime.now(timezone.utc).isoformat())
            now = datetime.now(tz)
            today = now.date().isoformat()
            if now.hour >= config.DIGEST_HOUR and db.get_meta("last_digest") != today:
                db.set_meta("last_digest", today)
                db.cleanup()
                send_digest()
        except Exception:
            logger.exception("Heartbeat failed")
        stop.wait(30)


def stats_text() -> str:
    st = db.get_stats()
    with counters_lock:
        c = dict(counters)
    return (
        f"👥 Всего: {st['total']}\n✅ Активных: {st['active']}\n"
        f"🚫 Заблокировали бота: {st['blocked']}\n🧠 С аналитикой: {st['analytics']}\n"
        f"💡 С фактами: {st['facts']}\n🌐 Языки: {st['langs'] or '—'}\n\n"
        f"📤 С момента запуска: отправлено {c.get('sent_ok', 0)}, "
        f"заблокировано {c.get('sent_blocked', 0)}, ошибок {c.get('sent_error', 0)}, "
        f"пропусков (нет данных) {c.get('skipped_no_data', 0)}, "
        f"алертов о движениях {c.get('alerts_sent', 0)}"
    )


def send_digest() -> None:
    alerts.notify("📈 <b>Ежедневный дайджест</b>\n" + stats_text(), key="digest", cooldown=0)
    with counters_lock:
        counters.clear()


# ------------------------------------------------------------------
# Команды пользователя
# ------------------------------------------------------------------
def prices_text(s: dict) -> str:
    """Курс + (если включена) закэшированная аналитика — без ожидания Gemini."""
    return M.compose(s, True, s["analytics_enabled"], False, ai_cached_only=True)


def handle_start(message) -> None:
    state = db.ensure_user(message.chat.id, message.from_user, subscribe=True)
    s = state.settings
    t = T[s["lang"]]
    head = t["start"].format(summary=summary(s))
    send(message.chat.id, head, markup=main_keyboard(s["lang"]))
    try:
        send(message.chat.id, prices_text(s), markup=settings_markup(s["lang"]))
    except Exception:
        logger.exception("start: prices failed for %s", message.chat.id)
        send(message.chat.id, t["err"])


def handle_top(message) -> None:
    s = db.ensure_user(message.chat.id, message.from_user).settings
    try:
        text = prices_text(s) or T[s["lang"]]["err"]
    except Exception:
        logger.exception("top: prices failed for %s", message.chat.id)
        text = T[s["lang"]]["err"]
    send(message.chat.id, text, markup=settings_markup(s["lang"]))


def handle_settings(message) -> None:
    s = db.ensure_user(message.chat.id, message.from_user).settings
    t = T[s["lang"]]
    markup = settings_markup(s["lang"])
    send(message.chat.id, t["settings"] if markup else t["no_webapp"], markup=markup)


def handle_stop(message) -> None:
    s = db.ensure_user(message.chat.id, message.from_user, touch=False).settings
    db.set_subscribed(message.chat.id, False)
    send(message.chat.id, T[s["lang"]]["stop"], markup=settings_markup(s["lang"]))


def handle_delete(message) -> None:
    s = db.ensure_user(message.chat.id, message.from_user, touch=False).settings
    t = T[s["lang"]]
    if (message.text or "").strip().lower().endswith("confirm"):
        db.delete_user(message.chat.id)
        send(message.chat.id, t["deleted"], markup=types.ReplyKeyboardRemove())
    else:
        send(message.chat.id, t["delete_hint"])


def guarded(handler):
    """Любая ошибка в обработчике: в лог (и алерт админу), пользователю — ничего не ломаем."""
    def wrapper(message):
        try:
            handler(message)
        except Exception:
            logger.exception("Handler %s failed (chat %s)", handler.__name__, message.chat.id)
    wrapper.__name__ = handler.__name__
    return wrapper


bot.message_handler(commands=["start"])(guarded(handle_start))
bot.message_handler(commands=["top"])(guarded(handle_top))
bot.message_handler(commands=["settings"])(guarded(handle_settings))
bot.message_handler(commands=["stop"])(guarded(handle_stop))
bot.message_handler(commands=["delete"])(guarded(handle_delete))


@bot.message_handler(commands=["help"])
@guarded
def on_help(message):
    s = db.ensure_user(message.chat.id, message.from_user, touch=False).settings
    send(message.chat.id, T[s["lang"]]["help"])


def _private_text_in(m, words: set) -> bool:
    return m.chat.type == "private" and bool(m.text) and m.text.strip().lower() in words


START_WORDS = {"start", "старт"}
TOP_WORDS = {"top", "топ"} | {T[x]["btn_top"].lower() for x in T}
SETTINGS_WORDS = {"settings", "настройки"} | {T[x]["btn_settings"].lower() for x in T}

bot.message_handler(func=lambda m: _private_text_in(m, START_WORDS))(guarded(handle_start))
bot.message_handler(func=lambda m: _private_text_in(m, TOP_WORDS))(guarded(handle_top))
bot.message_handler(func=lambda m: _private_text_in(m, SETTINGS_WORDS))(guarded(handle_settings))


# ------------------------------------------------------------------
# Команды админа
# ------------------------------------------------------------------
def is_admin(chat_id) -> bool:
    return config.ADMIN_CHAT_ID is not None and chat_id == config.ADMIN_CHAT_ID


@bot.message_handler(commands=["stats"], func=lambda m: is_admin(m.chat.id))
@guarded
def on_stats(message):
    send(message.chat.id, stats_text())


@bot.message_handler(commands=["health"], func=lambda m: is_admin(m.chat.id))
@guarded
def on_health(message):
    t0 = time.monotonic()
    db.get_meta("bot_heartbeat")
    db_ms = (time.monotonic() - t0) * 1000
    info = M.cache_info()
    up = int(time.time() - started_at)
    send(message.chat.id, (
        f"💚 <b>OK</b>\nАптайм: {up // 3600} ч {up % 3600 // 60} мин\nБД: {db_ms:.0f} мс\n"
        f"Кэш курсов (сек): {info['markets'] or '—'}\nКэш аналитики (сек): {info['ai'] or '—'}\n"
        f"Веб-приложение: {config.WEBAPP_URL or 'не настроено'}"))


@bot.message_handler(commands=["broadcast"], func=lambda m: is_admin(m.chat.id))
@guarded
def on_broadcast(message):
    text = (message.text or "").partition(" ")[2].strip()
    if not text:
        send(message.chat.id, "Использование: /broadcast текст сообщения")
        return
    pending_broadcast[message.chat.id] = text
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton("✅ Отправить всем", callback_data="bc:yes"),
           types.InlineKeyboardButton("❌ Отмена", callback_data="bc:no"))
    total = db.get_stats()["active"]
    bot.send_message(message.chat.id, f"Отправить {total} подписчикам?\n\n{text}", reply_markup=kb)


def run_broadcast(text: str, admin_id: int) -> None:
    body = html.escape(text, quote=False)
    ok = blocked = err = 0
    last_id = 0
    with ThreadPoolExecutor(max_workers=config.BROADCAST_WORKERS) as ex:
        while True:
            ids = db.active_ids(last_id)
            if not ids:
                break
            last_id = ids[-1]
            for res in ex.map(lambda cid: deliver((cid, body, "en", False)), ids):
                ok += res == "ok"
                blocked += res == "blocked"
                err += res == "error"
    alerts.notify(f"📣 Рассылка завершена: доставлено {ok}, заблокировали {blocked}, ошибок {err}",
                  key=f"bc:{time.time()}", cooldown=0)


@bot.callback_query_handler(func=lambda c: c.data in ("bc:yes", "bc:no"))
def on_broadcast_choice(call):
    try:
        if not is_admin(call.message.chat.id):
            return
        text = pending_broadcast.pop(call.message.chat.id, None)
        bot.answer_callback_query(call.id)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        if call.data == "bc:yes" and text:
            send(call.message.chat.id, "🚀 Рассылка запущена")
            threading.Thread(target=run_broadcast, args=(text, call.message.chat.id), daemon=True).start()
        else:
            send(call.message.chat.id, "Отменено")
    except Exception:
        logger.exception("broadcast callback failed")


# ------------------------------------------------------------------
# Запуск
# ------------------------------------------------------------------
def setup_telegram_ui() -> None:
    try:
        for lang, names in COMMANDS.items():
            cmds = [types.BotCommand(c, d) for c, d in zip(("top", "settings", "stop", "start", "help"), names)]
            bot.set_my_commands(cmds, language_code=None if lang == "en" else lang)
        if config.WEBAPP_URL:
            bot.set_chat_menu_button(menu_button=types.MenuButtonWebApp(
                type="web_app", text="⚙️ Settings", web_app=types.WebAppInfo(config.WEBAPP_URL)))
        else:
            logger.warning("WEBAPP_URL not set: settings button is disabled")
    except Exception:
        logger.exception("Failed to configure Telegram UI")


def shutdown(signum, frame) -> None:
    logger.info("Signal %s received, shutting down", signum)
    stop.set()
    bot.stop_polling()


def main() -> None:
    db.init_db()
    if config.USER_CHAT_IDS:
        db.seed_users(config.USER_CHAT_IDS)
    setup_telegram_ui()

    threads = [
        threading.Thread(target=dispatcher_loop, name="dispatcher"),
        threading.Thread(target=prepare_loop, name="prepare"),
        threading.Thread(target=heartbeat_loop, name="heartbeat"),
        threading.Thread(target=moves_loop, name="moves"),
    ]
    for th in threads:
        th.start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    alerts.notify("✅ Бот запущен", key="start", cooldown=0)
    logger.info("Bot started")
    try:
        bot.infinity_polling(
            timeout=60, long_polling_timeout=20,  # read-timeout = 60 с: запас на сетевые подвисания
            allowed_updates=["message", "callback_query"],
        )
    finally:
        stop.set()
        for th in threads:
            th.join(timeout=20)
        alerts.notify("⏹ Бот остановлен", key="stop", cooldown=0)
        alerts.flush()


if __name__ == "__main__":
    main()
