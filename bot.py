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
import game
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
                "/start — enable reports\n/game — play Up or Down\n/leaderboard — top players\n/profile — choose a profile\n/delete — delete my data",
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
                "/start — включить рассылку\n/game — игра «Вверх или вниз»\n/leaderboard — рейтинг игроков\n/profile — выбрать профиль\n/delete — удалить мои данные",
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
                "/stop — arrêter les envois\n/start — activer les envois\n/game — jeu hausse ou baisse\n/leaderboard — classement\n/profile — choisir un profil\n/delete — supprimer mes données",
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
                "/start — activar envíos\n/game — jugar: ¿sube o baja?\n/leaderboard — clasificación\n/profile — elegir un perfil\n/delete — borrar mis datos",
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
                "/start — Versand aktivieren\n/game — Spiel: Hoch oder runter\n/leaderboard — Rangliste\n/profile — Profil wählen\n/delete — meine Daten löschen",
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


T_EXTRA = {
    "en": {"btn_game": "🎮 Game",
           "ob_prof": "✨ <b>Pick your style</b> — I'll set everything up in one tap. You can fine-tune it later in ⚙️ Settings.\n\n{list}",
           "ob_custom_btn": "⚙️ I'll customize myself", "ob_done": "✅ <b>{name}</b> is set up!\n\n{summary}",
           "ob_custom": "👌 Defaults kept. Open settings to tune everything:",
           "ob_tz": "🕐 Your time zone is <b>{tz}</b> (UTC{off}). Reports arrive on the hour in this zone.",
           "ob_tz_btn": "🌍 Detect automatically", "ob_tz_ok_btn": "✅ That's right",
           "ob_tz_ok": "👍 Great! Reports will arrive in {tz} time."},
    "ru": {"btn_game": "🎮 Игра",
           "ob_prof": "✨ <b>Выберите стиль</b> — настрою всё одним нажатием. Потом можно подкрутить в ⚙️ Настройках.\n\n{list}",
           "ob_custom_btn": "⚙️ Настрою сам", "ob_done": "✅ Профиль <b>{name}</b> включён!\n\n{summary}",
           "ob_custom": "👌 Оставил настройки по умолчанию. Откройте настройки, чтобы всё подкрутить:",
           "ob_tz": "🕐 Ваш часовой пояс: <b>{tz}</b> (UTC{off}). Сообщения приходят ровно в начале часа по этому поясу.",
           "ob_tz_btn": "🌍 Определить автоматически", "ob_tz_ok_btn": "✅ Всё верно",
           "ob_tz_ok": "👍 Отлично! Сообщения будут приходить по времени {tz}."},
    "fr": {"btn_game": "🎮 Jeu",
           "ob_prof": "✨ <b>Choisissez votre style</b> — je configure tout en un clic. Vous pourrez affiner dans ⚙️ Paramètres.\n\n{list}",
           "ob_custom_btn": "⚙️ Je règle moi-même", "ob_done": "✅ Profil <b>{name}</b> activé !\n\n{summary}",
           "ob_custom": "👌 Réglages par défaut conservés. Ouvrez les paramètres pour tout ajuster :",
           "ob_tz": "🕐 Votre fuseau horaire : <b>{tz}</b> (UTC{off}). Les messages arrivent pile à l’heure dans ce fuseau.",
           "ob_tz_btn": "🌍 Détecter automatiquement", "ob_tz_ok_btn": "✅ C’est correct",
           "ob_tz_ok": "👍 Parfait ! Les messages arriveront à l’heure de {tz}."},
    "es": {"btn_game": "🎮 Juego",
           "ob_prof": "✨ <b>Elige tu estilo</b> — lo configuro todo con un toque. Luego puedes ajustarlo en ⚙️ Ajustes.\n\n{list}",
           "ob_custom_btn": "⚙️ Lo configuro yo", "ob_done": "✅ ¡Perfil <b>{name}</b> activado!\n\n{summary}",
           "ob_custom": "👌 Ajustes por defecto conservados. Abre los ajustes para afinarlo todo:",
           "ob_tz": "🕐 Tu zona horaria: <b>{tz}</b> (UTC{off}). Los mensajes llegan en punto en esta zona.",
           "ob_tz_btn": "🌍 Detectar automáticamente", "ob_tz_ok_btn": "✅ Es correcto",
           "ob_tz_ok": "👍 ¡Genial! Los mensajes llegarán en hora de {tz}."},
    "de": {"btn_game": "🎮 Spiel",
           "ob_prof": "✨ <b>Wählen Sie Ihren Stil</b> — ich richte alles mit einem Tipp ein. Später können Sie in ⚙️ Einstellungen feinjustieren.\n\n{list}",
           "ob_custom_btn": "⚙️ Ich stelle selbst ein", "ob_done": "✅ Profil <b>{name}</b> aktiviert!\n\n{summary}",
           "ob_custom": "👌 Standardeinstellungen bleiben. Öffnen Sie die Einstellungen zum Feinjustieren:",
           "ob_tz": "🕐 Ihre Zeitzone: <b>{tz}</b> (UTC{off}). Nachrichten kommen zur vollen Stunde in dieser Zeitzone.",
           "ob_tz_btn": "🌍 Automatisch erkennen", "ob_tz_ok_btn": "✅ Stimmt so",
           "ob_tz_ok": "👍 Super! Nachrichten kommen in {tz}-Zeit."},
}
for _l in T:
    T[_l].update(T_EXTRA[_l])

# стартовые профили: (название, описание)
PROF = {
    "en": {"beginner": ("🌱 Beginner", "Top 10 every 4 h, analytics twice a day, a fact every 3 h, only big-move alerts, quiet at night"),
           "trader": ("📈 Trader", "Top 15 every hour, analytics every 6 h, no facts, alerts from 3%"),
           "minimal": ("🧘 Minimalist", "One short top 5 a day at 9:00, only huge-move alerts, nothing else"),
           "explorer": ("🔎 Explorer", "Top 5 every 8 h, analytics twice a day, a fresh fact every hour, no alerts")},
    "ru": {"beginner": ("🌱 Новичок", "Топ-10 раз в 4 ч, аналитика дважды в день, факт раз в 3 ч, алерты только о крупных движениях, ночью тишина"),
           "trader": ("📈 Трейдер", "Топ-15 каждый час, аналитика раз в 6 ч, без фактов, алерты от 3%"),
           "minimal": ("🧘 Минималист", "Один короткий топ-5 в день в 9:00, только алерты о сильных движениях, больше ничего"),
           "explorer": ("🔎 Исследователь", "Топ-5 раз в 8 ч, аналитика дважды в день, свежий факт каждый час, без алертов")},
    "fr": {"beginner": ("🌱 Débutant", "Top 10 toutes les 4 h, analyse deux fois par jour, une anecdote toutes les 3 h, alertes seulement pour les gros mouvements, silence la nuit"),
           "trader": ("📈 Trader", "Top 15 chaque heure, analyse toutes les 6 h, pas d’anecdotes, alertes dès 3 %"),
           "minimal": ("🧘 Minimaliste", "Un top 5 par jour à 9 h, alertes seulement pour les très gros mouvements, rien d’autre"),
           "explorer": ("🔎 Explorateur", "Top 5 toutes les 8 h, analyse deux fois par jour, une nouvelle anecdote chaque heure, sans alertes")},
    "es": {"beginner": ("🌱 Principiante", "Top 10 cada 4 h, análisis dos veces al día, un dato cada 3 h, alertas solo de grandes movimientos, silencio por la noche"),
           "trader": ("📈 Trader", "Top 15 cada hora, análisis cada 6 h, sin datos curiosos, alertas desde 3 %"),
           "minimal": ("🧘 Minimalista", "Un top 5 al día a las 9:00, solo alertas de movimientos enormes, nada más"),
           "explorer": ("🔎 Explorador", "Top 5 cada 8 h, análisis dos veces al día, un dato nuevo cada hora, sin alertas")},
    "de": {"beginner": ("🌱 Einsteiger", "Top 10 alle 4 Std., Analyse zweimal täglich, alle 3 Std. ein Fakt, nur Alarme bei großen Bewegungen, nachts Ruhe"),
           "trader": ("📈 Trader", "Top 15 jede Stunde, Analyse alle 6 Std., keine Fakten, Alarme ab 3 %"),
           "minimal": ("🧘 Minimalist", "Einmal täglich um 9:00 ein kurzes Top 5, nur Alarme bei sehr starken Bewegungen, sonst nichts"),
           "explorer": ("🔎 Entdecker", "Top 5 alle 8 Std., Analyse zweimal täglich, jede Stunde ein neuer Fakt, keine Alarme")},
}

COMMANDS_EXTRA = {
    "en": ["Play Up or Down", "Leaderboard", "Choose a profile"],
    "ru": ["Игра «Вверх или вниз»", "Рейтинг игроков", "Выбрать профиль"],
    "fr": ["Jouer : hausse ou baisse", "Classement", "Choisir un profil"],
    "es": ["Jugar: ¿sube o baja?", "Clasificación", "Elegir un perfil"],
    "de": ["Spiel: Hoch oder runter", "Rangliste", "Profil wählen"],
}
LANG_BUTTONS = [("en", "🇬🇧 English"), ("ru", "🇷🇺 Русский"), ("fr", "🇫🇷 Français"),
                ("es", "🇪🇸 Español"), ("de", "🇩🇪 Deutsch")]


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
    """Кнопки под сообщениями: настройки (мини-приложение) и игра."""
    kb = types.InlineKeyboardMarkup()
    row = []
    if config.WEBAPP_URL:
        row.append(types.InlineKeyboardButton(
            T[lang]["btn_settings"], web_app=types.WebAppInfo(config.WEBAPP_URL)))
    row.append(types.InlineKeyboardButton(T[lang]["btn_game"], callback_data="g:new"))
    kb.row(*row)
    return kb


def main_keyboard(lang: str):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(T[lang]["btn_top"], T[lang]["btn_settings"])
    kb.row(T[lang]["btn_game"])
    return kb


def lang_picker_markup():
    kb = types.InlineKeyboardMarkup()
    for i in range(0, len(LANG_BUTTONS), 3):
        kb.row(*[types.InlineKeyboardButton(label, callback_data=f"ob:lang:{code}")
                 for code, label in LANG_BUTTONS[i:i + 3]])
    return kb


def profile_text(lang: str) -> str:
    lines = [f"<b>{PROF[lang][n][0]}</b> — {PROF[lang][n][1]}" for n in S.PROFILES]
    return T[lang]["ob_prof"].format(list="\n\n".join(lines))


def profile_markup(lang: str):
    kb = types.InlineKeyboardMarkup()
    names = list(S.PROFILES)
    for i in range(0, len(names), 2):
        kb.row(*[types.InlineKeyboardButton(PROF[lang][n][0], callback_data=f"ob:prof:{n}")
                 for n in names[i:i + 2]])
    kb.row(types.InlineKeyboardButton(T[lang]["ob_custom_btn"], callback_data="ob:prof:custom"))
    return kb


def tz_markup(lang: str):
    kb = types.InlineKeyboardMarkup()
    if config.WEBAPP_URL:
        kb.row(types.InlineKeyboardButton(T[lang]["ob_tz_btn"],
                                          web_app=types.WebAppInfo(config.WEBAPP_URL + "?mode=tz")))
    kb.row(types.InlineKeyboardButton(T[lang]["ob_tz_ok_btn"], callback_data="ob:tz:ok"))
    return kb


def utc_offset(tz_name: str) -> str:
    off = datetime.now(ZoneInfo(tz_name)).utcoffset().total_seconds()
    h, m = int(off // 3600), int(abs(off) % 3600 // 60)
    return f"{h:+d}" + (f":{m:02d}" if m else "")


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
    chat_id, text, lang, silent = item[:4]
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

        # факты берём из пула в БД: каждому пользователю тот, который он ещё не видел
        fact_chats = [j.chat_id for j in jobs if j.want_facts and not j.want_analytics]
        picked = {}
        if fact_chats:
            try:
                picked = db.pick_facts(fact_chats)
            except Exception:
                logger.exception("pick_facts failed")

        items = []
        for job in jobs:
            s = job.settings
            want_r = job.want_report and s["currency"] not in failed
            if job.want_report and not want_r:
                count("skipped_no_data")
            try:
                fact = picked.get(job.chat_id) if job.want_facts else None
                text = M.compose(s, want_r, job.want_analytics, job.want_facts,
                                 fact_text=M.format_fact(fact[1], s["lang"]) if fact else None)
            except Exception:
                logger.exception("compose failed for %s", job.chat_id)
                continue
            if text:
                # сообщение только с фактом приходит без звука
                silent = not (want_r or job.want_analytics)
                items.append((job.chat_id, text, s["lang"], silent, fact[0] if fact else None))

        if items:
            results = list(ex.map(deliver, items))
            seen = [(it[0], it[4]) for it, res in zip(items, results) if res == "ok" and it[4]]
            try:
                db.mark_facts_seen(seen)
            except Exception:
                logger.exception("mark_facts_seen failed")
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


def refill_facts(force: bool = False) -> None:
    """Пул фактов в БД: пополняем пачкой из 10 проверенных фактов, когда непоказанных осталось
    меньше 10, а также раз в 6 часов (вместе с обновлением аналитики)."""
    try:
        unused = db.count_unused_facts()
        last = db.get_meta("facts_last_refill")
        age_h = ((datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
                 if last else 1e9)
        if not force and unused >= 10 and age_h < 6:
            return
        batch = M.generate_fact_batch(10, db.recent_fact_topics(30))
        if batch:
            db.add_facts(batch)
            db.set_meta("facts_last_refill", datetime.now(timezone.utc).isoformat())
            logger.info("Fact pool: +%s verified facts (unused before: %s)", len(batch), unused)
        else:
            logger.warning("Fact pool refill produced no verified facts (unused: %s)", unused)
    except Exception:
        logger.exception("Fact pool refill failed")


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
            refill_facts()
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


def weekly_loop() -> None:
    """Итоги недели: по умолчанию в воскресенье 19:00 по времени пользователя."""
    stop.wait(45)
    while not stop.is_set():
        try:
            jobs = db.claim_weekly(200)
            if jobs:
                for cur in {s["currency"] for _, s in jobs}:
                    try:
                        M.get_markets(cur)
                    except Exception as e:
                        logger.error("Weekly: market data unavailable (%s): %s", cur, e)
                items = []
                for chat_id, s in jobs:
                    try:
                        text = M.compose_weekly(s, game.weekly_line(chat_id, s["lang"]))
                    except Exception:
                        logger.exception("weekly compose failed for %s", chat_id)
                        continue
                    if text:
                        items.append((chat_id, text, s["lang"], False))
                if items:
                    with ThreadPoolExecutor(max_workers=config.BROADCAST_WORKERS) as ex:
                        list(ex.map(deliver, items))
                    count("weekly_sent", len(items))
        except Exception:
            logger.exception("Weekly loop failed")
        stop.wait(60)


def game_loop() -> None:
    """Закрывает созревшие прогнозы игры и отправляет результаты."""
    stop.wait(30)
    while not stop.is_set():
        try:
            if db.game_due_count():
                prices = {c["id"]: c.get("current_price") for c in M.get_markets("usd")}
                for r in db.game_resolve_due(prices.get, game.score):
                    send(r["chat_id"], game.result_text(r), throttle=True, markup=game.after_markup(r["lang"]))
                    count("game_results")
        except Exception as e:
            logger.warning("Game loop error: %s", e)
        stop.wait(30)


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
        f"💡 С фактами: {st['facts']} (в пуле фактов: {db.facts_stats()[0]}, непоказанных: {db.facts_stats()[1]})\n"
        f"🌐 Языки: {st['langs'] or '—'}\n\n"
        f"📤 С момента запуска: отправлено {c.get('sent_ok', 0)}, "
        f"заблокировано {c.get('sent_blocked', 0)}, ошибок {c.get('sent_error', 0)}, "
        f"пропусков (нет данных) {c.get('skipped_no_data', 0)}, "
        f"алертов о движениях {c.get('alerts_sent', 0)}, итогов недели {c.get('weekly_sent', 0)}, "
        f"результатов игры {c.get('game_results', 0)}"
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
    is_new = not db.user_exists(message.chat.id)
    state = db.ensure_user(message.chat.id, message.from_user, subscribe=True)
    if is_new:  # онбординг: язык -> профиль -> часовой пояс
        send(message.chat.id, "🌍 <b>Choose your language · Выберите язык</b>", markup=lang_picker_markup())
        return
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


def handle_profile(message) -> None:
    s = db.ensure_user(message.chat.id, message.from_user, touch=False).settings
    send(message.chat.id, profile_text(s["lang"]), markup=profile_markup(s["lang"]))


def handle_game(message) -> None:
    s = db.ensure_user(message.chat.id, message.from_user, touch=False).settings
    try:
        text, kb = game.new_card(s["lang"])
    except Exception:
        logger.exception("game card failed")
        send(message.chat.id, T[s["lang"]]["err"])
        return
    send(message.chat.id, text, markup=kb)


def handle_leaderboard(message) -> None:
    s = db.ensure_user(message.chat.id, message.from_user, touch=False).settings
    text, kb = game.leaderboard(s["lang"], message.chat.id, "week")
    send(message.chat.id, text, markup=kb)


def handle_hidename(message) -> None:
    s = db.ensure_user(message.chat.id, message.from_user, touch=False).settings
    send(message.chat.id, game.toggle_hidden(s["lang"], message.chat.id))


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
bot.message_handler(commands=["profile"])(guarded(handle_profile))
bot.message_handler(commands=["game"])(guarded(handle_game))
bot.message_handler(commands=["leaderboard"])(guarded(handle_leaderboard))
bot.message_handler(commands=["hidename"])(guarded(handle_hidename))


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
GAME_WORDS = {"game", "игра"} | {T[x]["btn_game"].lower() for x in T}

bot.message_handler(func=lambda m: _private_text_in(m, START_WORDS))(guarded(handle_start))
bot.message_handler(func=lambda m: _private_text_in(m, TOP_WORDS))(guarded(handle_top))
bot.message_handler(func=lambda m: _private_text_in(m, SETTINGS_WORDS))(guarded(handle_settings))
bot.message_handler(func=lambda m: _private_text_in(m, GAME_WORDS))(guarded(handle_game))


# ------------------------------------------------------------------
# Кнопки: онбординг (ob:*) и игра (g:*)
# ------------------------------------------------------------------
def edit(call, text: str, markup=None) -> None:
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=markup)
    except ApiTelegramException as e:
        if "not modified" not in str(e).lower():
            raise


def on_onboarding(call, parts: list, chat_id: int) -> None:
    action = parts[1]
    if action == "lang" and parts[2] in S.LANGS:
        state = db.save_settings(chat_id, {"lang": parts[2]})
        lang = state.settings["lang"]
        edit(call, profile_text(lang), profile_markup(lang))
    elif action == "prof":
        lang = db.get_state(chat_id).settings["lang"]
        name = parts[2]
        if name == "custom":
            edit(call, T[lang]["ob_custom"], settings_markup(lang))
            return
        if name not in S.PROFILES:
            return
        s = db.save_settings(chat_id, S.PROFILES[name]).settings
        edit(call, T[lang]["ob_done"].format(name=PROF[lang][name][0], summary=summary(s)))
        try:
            send(chat_id, prices_text(s) or T[lang]["err"], markup=main_keyboard(lang))
        except Exception:
            logger.exception("onboarding: prices failed for %s", chat_id)
            send(chat_id, T[lang]["err"], markup=main_keyboard(lang))
        send(chat_id, T[lang]["ob_tz"].format(tz=s["tz"], off=utc_offset(s["tz"])), markup=tz_markup(lang))
    elif action == "tz":
        s = db.get_state(chat_id).settings
        edit(call, T[s["lang"]]["ob_tz_ok"].format(tz=s["tz"]))


def on_game(call, parts: list, chat_id: int, lang: str) -> None:
    action = parts[1]
    if action == "new":  # новая карточка отдельным сообщением (не затираем отчёт)
        text, kb = game.new_card(lang)
        send(chat_id, text, markup=kb)
    elif action == "next":
        text, kb = game.new_card(lang, exclude=parts[2])
        edit(call, text, kb)
    elif action == "p" and len(parts) == 5:
        text, kb, ok = game.place(chat_id, lang, parts[2], parts[3], int(parts[4]))
        edit(call, text, kb)
        count("game_predictions" if ok else "game_rejected")
    elif action == "lb":
        text, kb = game.leaderboard(lang, chat_id, "week" if parts[2] == "w" else "all")
        send(chat_id, text, markup=kb)
    elif action == "lbt":
        text, kb = game.leaderboard(lang, chat_id, "week" if parts[2] == "w" else "all")
        edit(call, text, kb)
    elif action == "me":
        text, kb = game.stats(lang, chat_id)
        send(chat_id, text, markup=kb)


@bot.callback_query_handler(func=lambda c: bool(c.data) and c.data.split(":")[0] in ("ob", "g"))
def on_callback(call):
    chat_id = call.message.chat.id
    try:
        lang = db.ensure_user(chat_id, call.from_user, touch=False).settings["lang"]
        parts = call.data.split(":")
        if parts[0] == "ob":
            on_onboarding(call, parts, chat_id)
        else:
            on_game(call, parts, chat_id, lang)
    except Exception:
        logger.exception("Callback %s failed (chat %s)", call.data, chat_id)
    finally:
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


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
            cmds = [types.BotCommand(c, d) for c, d in zip(
                ("top", "settings", "stop", "start", "help", "game", "leaderboard", "profile"),
                names + COMMANDS_EXTRA[lang])]
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
        threading.Thread(target=weekly_loop, name="weekly"),
        threading.Thread(target=game_loop, name="game"),
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
