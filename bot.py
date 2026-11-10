"""Telegram-бот: команды, персональное расписание рассылки, админ-инструменты."""
import collections
import contextlib
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

import requests
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

import alerts
import chart
import config
import db
import game
import help_texts
import market as M
import settings as S
import social
import tools

config.setup_logging("bot")
logger = logging.getLogger("bot")

bot = telebot.TeleBot(config.TOKEN, threaded=True, num_threads=config.BOT_THREADS)
stop = threading.Event()
started_at = time.time()

counters = collections.Counter()
counters_lock = threading.Lock()
pending_broadcast: dict = {}
BOT_USERNAME = None  # заполняется при старте (get_me): нужен для реферальных ссылок
INLINE_OK = False  # включён ли inline-режим в @BotFather (/setinline)


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

T_V2 = {
    "en": {
        "start": "👋 <b>Hi!</b> I'm your crypto assistant: prices, AI analytics, price alerts, portfolio and a prediction game.\n\n"
                 "{summary}\n\n🔎 Send any ticker — <b>BTC</b>, <b>ETH</b> — for a coin card. /help — everything I can do.",
        "help": "📖 <b>What I can do</b>\n\n"
                "🔎 Send any ticker — <b>BTC</b>, <b>eth</b>, <b>solana</b> — for a coin card\n\n"
                "/top — prices now\n/price BTC — coin card · /chart BTC — price chart\n"
                "/alerts — price alerts · <code>/alert BTC 100000</code>\n"
                "/portfolio — your portfolio · <code>/add BTC 0.5</code>\n"
                "/game — Up or Down? · /leaderboard — top players\n"
                "/invite — invite friends (+50 game points each)\n"
                "/settings — schedule, coins, language · /profile — presets\n"
                "/stop — pause reports · /start — resume\n/delete — delete my data",
        "btn_pf": "💼 Portfolio", "btn_alerts": "🔔 Alerts", "btn_invite": "🎁 Invite", "btn_share": "📤 Share",
        "ob_lang_btn": "🌍 Language",
        "tips": "💡 <b>Quick tips</b>\n• Send any ticker — <b>BTC</b>, <b>ETH</b>… — to get a coin card\n"
                "• 🔔 /alerts — “tell me when BTC hits 100k”\n• 💼 /portfolio — track what you hold\n"
                "• 🎯 /game — predict prices and keep a daily streak 🔥\n• 🎁 /invite — bring friends, earn points",
        "flood": "⏳ Too many requests — please slow down a little.",
    },
    "ru": {
        "start": "👋 <b>Привет!</b> Я ваш крипто-помощник: курсы, AI-аналитика, ценовые алерты, портфель и игра-прогноз.\n\n"
                 "{summary}\n\n🔎 Отправьте любой тикер — <b>BTC</b>, <b>ETH</b> — и получите карточку монеты. /help — всё, что я умею.",
        "help": "📖 <b>Что я умею</b>\n\n"
                "🔎 Отправьте любой тикер — <b>BTC</b>, <b>eth</b>, <b>биткоин</b> — и получите карточку монеты\n\n"
                "/top — курс сейчас\n/price BTC — карточка монеты · /chart BTC — график\n"
                "/alerts — ценовые алерты · <code>/alert BTC 100000</code>\n"
                "/portfolio — ваш портфель · <code>/add BTC 0.5</code>\n"
                "/game — «Вверх или вниз?» · /leaderboard — рейтинг\n"
                "/invite — пригласить друзей (+50 баллов за каждого)\n"
                "/settings — расписание, монеты, язык · /profile — профили\n"
                "/stop — пауза рассылки · /start — включить\n/delete — удалить мои данные",
        "btn_pf": "💼 Портфель", "btn_alerts": "🔔 Алерты", "btn_invite": "🎁 Пригласить", "btn_share": "📤 Поделиться",
        "ob_lang_btn": "🌍 Язык",
        "tips": "💡 <b>Пара подсказок</b>\n• Отправьте любой тикер — <b>BTC</b>, <b>ETH</b>… — и получите карточку монеты\n"
                "• 🔔 /alerts — «напиши, когда BTC будет 100k»\n• 💼 /portfolio — следите за своими монетами\n"
                "• 🎯 /game — прогнозируйте цену и держите серию дней 🔥\n• 🎁 /invite — зовите друзей и получайте баллы",
        "flood": "⏳ Слишком много запросов — чуть помедленнее, пожалуйста.",
    },
    "fr": {
        "start": "👋 <b>Salut !</b> Je suis votre assistant crypto : cours, analyses IA, alertes de prix, portefeuille et jeu de pronostics.\n\n"
                 "{summary}\n\n🔎 Envoyez un ticker — <b>BTC</b>, <b>ETH</b> — pour sa fiche. /help — tout ce que je sais faire.",
        "help": "📖 <b>Ce que je sais faire</b>\n\n"
                "🔎 Envoyez un ticker — <b>BTC</b>, <b>eth</b>, <b>solana</b> — pour la fiche de la crypto\n\n"
                "/top — cours maintenant\n/price BTC — fiche d’une crypto · /chart BTC — graphique\n"
                "/alerts — alertes de prix · <code>/alert BTC 100000</code>\n"
                "/portfolio — votre portefeuille · <code>/add BTC 0.5</code>\n"
                "/game — hausse ou baisse ? · /leaderboard — classement\n"
                "/invite — inviter des amis (+50 points chacun)\n"
                "/settings — planning, cryptos, langue · /profile — profils\n"
                "/stop — mettre en pause · /start — reprendre\n/delete — supprimer mes données",
        "btn_pf": "💼 Portefeuille", "btn_alerts": "🔔 Alertes", "btn_invite": "🎁 Inviter", "btn_share": "📤 Partager",
        "ob_lang_btn": "🌍 Langue",
        "tips": "💡 <b>Astuces</b>\n• Envoyez un ticker — <b>BTC</b>, <b>ETH</b>… — pour la fiche de la crypto\n"
                "• 🔔 /alerts — « préviens-moi quand BTC atteint 100k »\n• 💼 /portfolio — suivez vos avoirs\n"
                "• 🎯 /game — pronostiquez et gardez votre série quotidienne 🔥\n• 🎁 /invite — invitez des amis, gagnez des points",
        "flood": "⏳ Trop de requêtes — ralentissez un peu, s’il vous plaît.",
    },
    "es": {
        "start": "👋 <b>¡Hola!</b> Soy tu asistente cripto: precios, análisis con IA, alertas de precio, cartera y un juego de predicciones.\n\n"
                 "{summary}\n\n🔎 Envía cualquier ticker — <b>BTC</b>, <b>ETH</b> — para ver su ficha. /help — todo lo que sé hacer.",
        "help": "📖 <b>Qué sé hacer</b>\n\n"
                "🔎 Envía cualquier ticker — <b>BTC</b>, <b>eth</b>, <b>solana</b> — para ver la ficha de la moneda\n\n"
                "/top — precios ahora\n/price BTC — ficha de moneda · /chart BTC — gráfico\n"
                "/alerts — alertas de precio · <code>/alert BTC 100000</code>\n"
                "/portfolio — tu cartera · <code>/add BTC 0.5</code>\n"
                "/game — ¿sube o baja? · /leaderboard — clasificación\n"
                "/invite — invitar amigos (+50 puntos por cada uno)\n"
                "/settings — horario, monedas, idioma · /profile — perfiles\n"
                "/stop — pausar envíos · /start — reanudar\n/delete — borrar mis datos",
        "btn_pf": "💼 Cartera", "btn_alerts": "🔔 Alertas", "btn_invite": "🎁 Invitar", "btn_share": "📤 Compartir",
        "ob_lang_btn": "🌍 Idioma",
        "tips": "💡 <b>Consejos</b>\n• Envía cualquier ticker — <b>BTC</b>, <b>ETH</b>… — para ver su ficha\n"
                "• 🔔 /alerts — «avísame cuando BTC llegue a 100k»\n• 💼 /portfolio — sigue lo que tienes\n"
                "• 🎯 /game — predice precios y mantén tu racha diaria 🔥\n• 🎁 /invite — invita amigos y gana puntos",
        "flood": "⏳ Demasiadas solicitudes — ve un poco más despacio, por favor.",
    },
    "de": {
        "start": "👋 <b>Hallo!</b> Ich bin Ihr Krypto-Assistent: Kurse, KI-Analysen, Preisalarme, Portfolio und ein Tippspiel.\n\n"
                 "{summary}\n\n🔎 Senden Sie einen Ticker — <b>BTC</b>, <b>ETH</b> — für die Coin-Karte. /help — alle Funktionen.",
        "help": "📖 <b>Was ich kann</b>\n\n"
                "🔎 Senden Sie einen Ticker — <b>BTC</b>, <b>eth</b>, <b>solana</b> — für die Coin-Karte\n\n"
                "/top — Kurse jetzt\n/price BTC — Coin-Karte · /chart BTC — Kurschart\n"
                "/alerts — Preisalarme · <code>/alert BTC 100000</code>\n"
                "/portfolio — Ihr Portfolio · <code>/add BTC 0.5</code>\n"
                "/game — Hoch oder runter? · /leaderboard — Rangliste\n"
                "/invite — Freunde einladen (+50 Punkte pro Freund)\n"
                "/settings — Zeitplan, Coins, Sprache · /profile — Profile\n"
                "/stop — Versand pausieren · /start — fortsetzen\n/delete — meine Daten löschen",
        "btn_pf": "💼 Portfolio", "btn_alerts": "🔔 Alarme", "btn_invite": "🎁 Einladen", "btn_share": "📤 Teilen",
        "ob_lang_btn": "🌍 Sprache",
        "tips": "💡 <b>Kurze Tipps</b>\n• Senden Sie einen Ticker — <b>BTC</b>, <b>ETH</b>… — für die Coin-Karte\n"
                "• 🔔 /alerts — „Sag Bescheid, wenn BTC 100k erreicht“\n• 💼 /portfolio — Bestände verfolgen\n"
                "• 🎯 /game — Kurse tippen und die Tagesserie halten 🔥\n• 🎁 /invite — Freunde einladen, Punkte sammeln",
        "flood": "⏳ Zu viele Anfragen — bitte etwas langsamer.",
    },
}
for _l in T:
    T[_l].update(T_V2[_l])
    T[_l]["help"] = help_texts.HELP[_l]  # подробная справка по разделам ({bot} — имя бота)
    T[_l]["group_settings"] = help_texts.GROUP_SETTINGS[_l]

# меню команд Telegram (порядок важен: самые нужные сверху)
CMD_ORDER = ["top", "price", "chart", "alerts", "portfolio", "game", "leaderboard", "invite", "settings",
             "profile", "stop", "start", "help"]
CMD_DESC = {
    "en": ["Prices now", "Coin card (e.g. /price BTC)", "Price chart (/chart BTC 7d)", "Price alerts", "My portfolio", "Play Up or Down",
           "Leaderboard", "Invite friends", "Settings", "Choose a profile", "Stop reports", "Start reports", "Help"],
    "ru": ["Курс сейчас", "Карточка монеты (/price BTC)", "График цены (/chart BTC 7d)", "Ценовые алерты", "Мой портфель", "Игра «Вверх или вниз»",
           "Рейтинг игроков", "Пригласить друзей", "Настройки", "Выбрать профиль", "Отключить рассылку",
           "Включить рассылку", "Помощь"],
    "fr": ["Cours maintenant", "Fiche d’une crypto (/price BTC)", "Graphique du cours (/chart BTC 7d)", "Alertes de prix", "Mon portefeuille",
           "Jouer : hausse ou baisse", "Classement", "Inviter des amis", "Paramètres", "Choisir un profil",
           "Arrêter les envois", "Activer les envois", "Aide"],
    "es": ["Precios ahora", "Ficha de moneda (/price BTC)", "Gráfico de precio (/chart BTC 7d)", "Alertas de precio", "Mi cartera", "Jugar: ¿sube o baja?",
           "Clasificación", "Invitar amigos", "Ajustes", "Elegir un perfil", "Detener envíos", "Activar envíos", "Ayuda"],
    "de": ["Kurse jetzt", "Coin-Karte (/price BTC)", "Kurschart (/chart BTC 7d)", "Preisalarme", "Mein Portfolio", "Spiel: Hoch oder runter",
           "Rangliste", "Freunde einladen", "Einstellungen", "Profil wählen", "Versand stoppen",
           "Versand aktivieren", "Hilfe"],
}

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
def settings_markup(lang: str, share: bool = False):
    """Кнопки под сообщениями: настройки (мини-приложение) и игра; share — ещё «Поделиться»."""
    kb = types.InlineKeyboardMarkup()
    row = []
    if config.WEBAPP_URL:
        row.append(types.InlineKeyboardButton(
            T[lang]["btn_settings"], web_app=types.WebAppInfo(config.WEBAPP_URL)))
    row.append(types.InlineKeyboardButton(T[lang]["btn_game"], callback_data="g:new"))
    kb.row(*row)
    if share and INLINE_OK:
        kb.row(social.ShareButton(T[lang]["btn_share"]))
    return kb


def main_keyboard(lang: str):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    kb.row(T[lang]["btn_top"], T[lang]["btn_pf"])
    kb.row(T[lang]["btn_alerts"], T[lang]["btn_game"])
    kb.row(T[lang]["btn_settings"], T[lang]["btn_invite"])
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


def profile_markup(lang: str, lang_btn: bool = False):
    kb = types.InlineKeyboardMarkup()
    names = list(S.PROFILES)
    for i in range(0, len(names), 2):
        kb.row(*[types.InlineKeyboardButton(PROF[lang][n][0], callback_data=f"ob:prof:{n}")
                 for n in names[i:i + 2]])
    kb.row(types.InlineKeyboardButton(T[lang]["ob_custom_btn"], callback_data="ob:prof:custom"))
    if lang_btn:  # язык определили автоматически — даём сменить
        kb.row(types.InlineKeyboardButton(T[lang]["ob_lang_btn"], callback_data="ob:langs"))
    return kb


def tz_markup(lang: str):
    kb = types.InlineKeyboardMarkup()
    if config.WEBAPP_URL:
        kb.row(types.InlineKeyboardButton(T[lang]["ob_tz_btn"],
                                          web_app=types.WebAppInfo(config.WEBAPP_URL + "?mode=tz")))
    kb.row(types.InlineKeyboardButton(T[lang]["ob_tz_ok_btn"], callback_data="ob:tz:ok"))
    return kb


def utc_offset(tz_name: str) -> str:
    off = int(datetime.now(ZoneInfo(tz_name)).utcoffset().total_seconds())
    sign, off = ("-" if off < 0 else "+"), abs(off)  # -3:30, а не -4:30 (Newfoundland и т.п.)
    h, m = off // 3600, off % 3600 // 60
    return f"{sign}{h}" + (f":{m:02d}" if m else "")


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
# один общий пул потоков для всех рассылок (отчёты, алерты, итоги недели, /broadcast):
# потоки не создаются заново каждые несколько минут, а общий лимит скорости всё равно один
sender = ThreadPoolExecutor(max_workers=config.BROADCAST_WORKERS, thread_name_prefix="send")


def is_group(chat_id) -> bool:
    return int(chat_id) < 0  # у групп и каналов отрицательные id


def for_chat(chat_id, markup):
    """В группах Telegram запрещает кнопки мини-приложения (web_app) и отклоняет из-за них всё
    сообщение; нижняя клавиатура там мешает всем участникам. Убираем и то и другое."""
    if markup is None or not is_group(chat_id):
        return markup
    if isinstance(markup, types.ReplyKeyboardMarkup):
        return None
    if isinstance(markup, types.InlineKeyboardMarkup):
        rows = [[b for b in row if b.web_app is None] for row in markup.keyboard]
        rows = [r for r in rows if r]
        if not rows:
            return None
        kb = types.InlineKeyboardMarkup()
        for r in rows:
            kb.row(*r)
        return kb
    return markup


def send(chat_id, text: str, throttle: bool = False, markup=None, silent: bool = False) -> str:
    """Возвращает 'ok' | 'blocked' | 'error'."""
    parse_mode = "HTML"
    markup = for_chat(chat_id, markup)
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
    """item: (chat_id, text, lang, silent[, fact_id[, markup]])"""
    chat_id, text, lang, silent = item[:4]
    markup = item[5] if len(item) > 5 and item[5] is not None else settings_markup(lang)
    result = send(chat_id, text, throttle=True, markup=markup, silent=silent)
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
IDLE_MAX_WAIT = 300  # даже без сигналов перепроверяем расписание не реже раза в 5 минут


class Waker:
    """Ожидание диспетчера: до ближайшего слота или до сигнала NOTIFY (кнопка «Отправить сейчас»,
    изменение настроек, остановка бота). Раньше диспетчер опрашивал базу каждую секунду
    (~86 тыс. запросов в сутки); теперь в тишине — пара запросов в 5 минут."""

    def __init__(self):
        self.conn = None

    def _connect(self):
        import psycopg
        self.conn = psycopg.connect(config.DATABASE_URL, autocommit=True)
        self.conn.execute(f"LISTEN {db.WAKE_CHANNEL}")

    def wait(self, seconds: float) -> None:
        seconds = max(0.2, min(seconds, IDLE_MAX_WAIT))
        try:
            if self.conn is None or self.conn.closed:
                self._connect()
            for _ in self.conn.notifies(timeout=seconds, stop_after=1):
                pass
        except Exception as e:  # база перезапускается и т.п.: ждём по-простому и переподключаемся
            logger.warning("Dispatcher wake channel unavailable (%s), polling", e)
            self.close()
            stop.wait(min(seconds, 5))

    def close(self) -> None:
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass
        self.conn = None


def _idle_wait(waker: "Waker") -> None:
    try:
        due = db.next_due()
    except Exception:
        logger.exception("Dispatcher: next_due failed")
        stop.wait(5)
        return
    if due is None:
        waker.wait(IDLE_MAX_WAIT)
    else:
        waker.wait((due - datetime.now(timezone.utc)).total_seconds() + 0.2)


def dispatcher_loop() -> None:
    ex = sender
    waker = Waker()
    while not stop.is_set():
        try:
            jobs, claimed, max_lag = db.claim_due(config.DISPATCH_BATCH)
        except Exception:
            logger.exception("Dispatcher: claim_due failed")
            stop.wait(5)
            continue

        if claimed == 0:
            _idle_wait(waker)
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

        # портфель (короткая строка в отчёте) — одним запросом на пачку
        holdings = {}
        pf_chats = [j.chat_id for j in jobs if j.want_report and j.settings["show_portfolio"]]
        if pf_chats:
            try:
                holdings = db.holdings_for(pf_chats)
            except Exception:
                logger.exception("holdings_for failed")

        items = []
        for job in jobs:
            s = job.settings
            want_r = job.want_report and s["currency"] not in failed
            if job.want_report and not want_r:
                count("skipped_no_data")
            try:
                fact = picked.get(job.chat_id) if job.want_facts else None
                pf = tools.portfolio_line(s, holdings.get(job.chat_id)) if want_r else None
                text = M.compose(s, want_r, job.want_analytics, job.want_facts,
                                 fact_text=M.format_fact(fact[1], s["lang"]) if fact else None,
                                 portfolio_text=pf)
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
    waker.close()


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


def _hours_since(iso) -> float:
    if not iso:
        return 1e9
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600


def refill_facts(force: bool = False) -> None:
    """Пул фактов в БД пополняется редко: пачкой FACT_BATCH проверенных фактов (2 запроса к
    Gemini), когда непоказанных осталось меньше пачки и прошло 6 часов с прошлого пополнения
    (или совсем мало осталось). Это примерно 2 пополнения в сутки. После неудачи пауза час."""
    try:
        unused = db.count_unused_facts()
        need = unused < 5 or (unused < config.FACT_BATCH and _hours_since(db.get_meta("facts_last_refill")) >= 6)
        if not force and (not need or _hours_since(db.get_meta("facts_last_attempt")) < 1):
            return
        db.set_meta("facts_last_attempt", datetime.now(timezone.utc).isoformat())
        batch = M.generate_fact_batch(config.FACT_BATCH, db.recent_fact_topics(30))
        if batch:
            db.add_facts(batch)
            db.set_meta("facts_last_refill", datetime.now(timezone.utc).isoformat())
            logger.info("Fact pool: +%s verified facts (unused before: %s)", len(batch), unused)
        else:
            logger.warning("Fact pool refill produced no verified facts (unused: %s)", unused)
    except Exception:
        logger.exception("Fact pool refill failed")


def prepare() -> None:
    try:
        currencies, ana_langs, fact_langs = db.active_currencies_langs()
        # к CoinGecko — один запрос в USD; остальные валюты пересчитываются по его курсам
        try:
            data = M.get_markets("usd", max_age=0)
            if M.source("usd") == "coingecko":  # список монет для мини-приложения
                db.set_meta("top_coins", json.dumps(M.top_coins_snapshot(data), ensure_ascii=False))
            for cur in set(currencies) - {"usd"}:
                M.get_markets(cur)  # прогрев пересчёта (без запросов к API, кроме курсов раз в 10 мин)
        except Exception as e:
            logger.error("Prepare: market data unavailable: %s", e)
        M.get_indices(max_age=0)
        # к Gemini обращаемся редко: аналитика обновляется, только когда кэш старше AI_CACHE_MIN
        # (≈4 раза в сутки), факты пополняются пачкой ~2 раза в сутки; один запрос — все языки
        if ana_langs:
            M.get_ai_text("analysis", ana_langs[0])
        if fact_langs:
            refill_facts()
    except Exception:
        logger.exception("Prepare step failed")


def prepare_loop() -> None:
    """Прогрев при старте, затем в :28 и :58 каждого часа: обновляет курсы; аналитика и пул
    фактов обновляются только по необходимости (см. prepare). Пользователям всё отдаётся из кэша."""
    prepare()
    while not stop.is_set():
        t = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
        while t.minute not in (28, 58):
            t += timedelta(minutes=1)
        if not _sleep_until(t):
            return
        prepare()


def check_moves() -> None:
    """Ищет резкие движения за 1 час и шлёт пользователям алерты по их монетам."""
    try:
        data = M.get_markets("usd")  # данные не старше CACHE_TTL: лишний запрос к API не нужен
    except Exception as e:
        logger.warning("Move check skipped, no market data: %s", e)
        return
    movers = M.find_movers(data, 3.0)  # 3% — минимальный порог из настроек
    if not movers:
        return
    now = datetime.now(timezone.utc)
    last_id, sent = 0, 0
    with contextlib.nullcontext(sender) as ex:  # общий пул: не закрываем его после рассылки
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
                holdings = db.holdings_for([c for c, _ in jobs])
                for chat_id, s in jobs:
                    try:
                        pf = tools.portfolio_line(s, holdings.get(chat_id), weekly=True)
                        text = M.compose_weekly(s, game.weekly_line(chat_id, s["lang"]), portfolio_text=pf)
                    except Exception:
                        logger.exception("weekly compose failed for %s", chat_id)
                        continue
                    if text:
                        items.append((chat_id, text, s["lang"], False, None,
                                      settings_markup(s["lang"], share=True)))
                if items:
                    list(sender.map(deliver, items))
                    count("weekly_sent", len(items))
        except Exception:
            logger.exception("Weekly loop failed")
        stop.wait(60)


REMIND_HOUR = 20  # локальный час напоминания «не потеряйте серию»


def send_streak_reminders() -> None:
    """Раз в день (в 20:00 по времени игрока) напоминает о серии, если сегодня он ещё не играл."""
    now = datetime.now(timezone.utc)
    for chat_id, streak, last_play, reminded_on, s in db.game_streak_candidates():
        if not s["game_reminders"]:
            continue
        local = now.astimezone(ZoneInfo(s["tz"]))
        today = local.date()
        if (local.hour != REMIND_HOUR or last_play != today - timedelta(days=1)
                or reminded_on == today or not S.is_allowed_now(s, now)):
            continue
        db.game_mark_reminded(chat_id, today)  # до отправки: не дублируем при сбоях
        text, kb = game.reminder(s["lang"], streak)
        res = send(chat_id, text, throttle=True, markup=kb)
        if res == "blocked":
            db.mark_blocked(chat_id)
        count("streak_reminders")


def price_alerts_loop() -> None:
    """Раз в минуту проверяет ценовые алерты («сообщи, когда BTC будет $100k»)."""
    stop.wait(20)
    while not stop.is_set():
        try:
            now = datetime.now(timezone.utc)
            items = [(chat_id, text, lang, not S.is_allowed_now(s, now), None, kb)
                     for chat_id, text, lang, s, kb in tools.check_price_alerts()]
            if items:
                results = list(sender.map(deliver, items))
                count("price_alerts_sent", sum(1 for r in results if r == "ok"))
        except Exception:
            logger.exception("Price alerts check failed")
        stop.wait(60)


def game_loop() -> None:
    """Закрывает созревшие прогнозы игры и отправляет результаты; напоминает о серии дней."""
    stop.wait(30)
    last_remind = 0.0
    while not stop.is_set():
        if time.time() - last_remind > 300:
            last_remind = time.time()
            try:
                send_streak_reminders()
            except Exception:
                logger.exception("Streak reminders failed")
        try:
            if db.game_due_count():
                prices = {c["id"]: c.get("current_price") for c in M.get_markets("usd")}
                for r in db.game_resolve_due(prices.get, game.score):
                    res = send(r["chat_id"], game.result_text(r), throttle=True,
                               markup=game.after_markup(r["lang"]))
                    if res == "blocked":
                        db.mark_blocked(r["chat_id"])
                    count("game_results")
        except Exception as e:
            logger.warning("Game loop error: %s", e)
        stop.wait(30)


def refresh_inline() -> None:
    """Подхватывает включение inline-режима (@BotFather -> /setinline) без перезапуска."""
    global INLINE_OK, BOT_USERNAME
    try:
        me = bot.get_me()
    except Exception:
        return
    BOT_USERNAME = me.username or BOT_USERNAME
    if me.supports_inline_queries and not INLINE_OK:
        INLINE_OK = True
        logger.info("Inline mode is now enabled: sharing buttons are on")


def heartbeat_loop() -> None:
    tz = ZoneInfo(config.DEFAULT_TZ)
    last_identity = time.time()
    while not stop.is_set():
        # после старта без интернета (например, после отключения света) донастраиваемся сами:
        # имя бота и меню команд — раз в минуту, включение inline-режима — раз в 10 минут
        missing = not BOT_USERNAME or not UI_READY
        if (missing and time.time() - last_identity > 60) or \
                (not INLINE_OK and time.time() - last_identity > 600):
            last_identity = time.time()
            refresh_inline()
            if not UI_READY and BOT_USERNAME:
                setup_telegram_ui()
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
    facts_total, facts_unused = db.facts_stats()
    with counters_lock:
        c = dict(counters)
    return (
        f"👥 Всего: {st['total']}\n✅ Подписаны на рассылку: {st['active']}\n"
        f"📅 DAU: {st['dau']} · WAU: {st['wau']}\n"
        f"🆕 Новых за сутки: {st['new_1d']} · за 7 дней: {st['new_7d']} (по приглашениям: {st['ref_7d']})\n"
        f"🔔 Ценовых алертов: {st['price_alerts']} · 💼 Портфелей: {st['portfolios']} · "
        f"🎯 Играли за 2 дня: {st['players_2d']}\n"
        f"🚫 Заблокировали бота: {st['blocked']}\n🧠 С аналитикой: {st['analytics']}\n"
        f"💡 С фактами: {st['facts']} (в пуле фактов: {facts_total}, непоказанных: {facts_unused})\n"
        f"🌐 Языки: {st['langs'] or '—'}\n\n"
        f"📤 С момента запуска: отправлено {c.get('sent_ok', 0)}, "
        f"заблокировано {c.get('sent_blocked', 0)}, ошибок {c.get('sent_error', 0)}, "
        f"пропусков (нет данных) {c.get('skipped_no_data', 0)}, "
        f"алертов о движениях {c.get('alerts_sent', 0)}, итогов недели {c.get('weekly_sent', 0)}, "
        f"результатов игры {c.get('game_results', 0)}, ценовых алертов {c.get('price_alerts_sent', 0)}, "
        f"напоминаний о серии {c.get('streak_reminders', 0)}, новых пользователей {c.get('new_users', 0)}"
    )


def send_digest() -> None:
    alerts.notify("📈 <b>Ежедневный дайджест</b>\n" + stats_text(), key="digest", cooldown=0)
    with counters_lock:
        counters.clear()


# ------------------------------------------------------------------
# Команды пользователя
# ------------------------------------------------------------------
def prices_text(s: dict, chat_id: int = None) -> str:
    """Курс + (если включена) закэшированная аналитика — без ожидания Gemini; плюс строка портфеля."""
    pf = tools.portfolio_line(s, db.holdings(chat_id)) if chat_id else None
    return M.compose(s, True, s["analytics_enabled"], False, ai_cached_only=True, portfolio_text=pf)


# --- защита от флуда: не больше 20 действий за 10 секунд на пользователя ---
_flood: dict = collections.defaultdict(collections.deque)
_flood_lock = threading.Lock()
FLOOD_LIMIT, FLOOD_WINDOW = 20, 10


def flooded(chat_id: int) -> bool:
    if is_admin(chat_id):
        return False
    now = time.monotonic()
    with _flood_lock:
        q = _flood[chat_id]
        while q and now - q[0] > FLOOD_WINDOW:
            q.popleft()
        q.append(now)
        if len(_flood) > 20000:
            for k in [k for k, v in _flood.items() if not v or now - v[-1] > FLOOD_WINDOW]:
                _flood.pop(k, None)
        return len(q) > FLOOD_LIMIT


def user(message, touch: bool = True) -> dict:
    return db.ensure_user(message.chat.id, message.from_user, touch=touch).settings


def local_today(s: dict):
    return datetime.now(ZoneInfo(s["tz"])).date()


def ask(chat_id: int, text: str, placeholder: str = None) -> None:
    """Вопрос с полем ответа (ForceReply): пользователю достаточно просто ввести значение."""
    send(chat_id, text, markup=types.ForceReply(input_field_placeholder=placeholder))


def show_card(chat_id: int, s: dict, coin_id: str, call=None) -> bool:
    res = tools.card(chat_id, s, coin_id, share=INLINE_OK)
    if res is None:
        return False
    text, kb = res
    if call is not None:
        edit(call, text, kb)
    else:
        send(chat_id, text, markup=kb)
    count("coin_cards")
    return True


def chart_markup(lang: str, coin: dict, days: int):
    ct, cid = chart.CT[lang], coin["id"]
    kb = types.InlineKeyboardMarkup()
    kb.row(*[types.InlineKeyboardButton(("✅ " if d == days else "") + ct["p"][d], callback_data=f"ch:p:{cid}:{d}")
             for d in chart.PERIODS])
    row = [types.InlineKeyboardButton(ct["card"], callback_data=f"c:o:{cid}"),
           types.InlineKeyboardButton(tools.TT[lang]["btn_alert"], callback_data=f"pa:menu:{cid}")]
    kb.row(*row)
    if INLINE_OK:
        kb.row(social.ShareButton(tools.TT[lang]["btn_share"], coin["symbol"].upper()))
    return kb


def send_chart(chat_id: int, s: dict, coin_id: str, days: int, call=None) -> None:
    """График цены картинкой; call — переключение периода в том же сообщении."""
    lang = s["lang"]
    days = days if days in chart.PERIODS else 1
    coin = tools._coin_in(s["currency"], coin_id)
    if coin is None:
        send(chat_id, tools.TT[lang]["not_found"].format(q=html.escape(coin_id)))
        return
    try:
        bot.send_chat_action(chat_id, "upload_photo")
    except Exception:
        pass
    try:
        watermark = f"@{BOT_USERNAME}" if BOT_USERNAME else ""
        png, caption = chart.build(coin, s["currency"], days, s["tz"], lang, watermark)
    except Exception as e:
        logger.warning("chart failed for %s %s: %s", coin_id, days, e)
        send(chat_id, chart.CT[lang]["fail"])
        return
    kb = chart_markup(lang, coin, days)
    try:
        if call is not None:
            res = bot.edit_message_media(types.InputMediaPhoto(png, caption=caption, parse_mode="HTML"),
                                         chat_id, call.message.message_id, reply_markup=kb)
        else:
            res = bot.send_photo(chat_id, png, caption=caption, parse_mode="HTML", reply_markup=kb)
        if isinstance(png, bytes) and getattr(res, "photo", None):
            chart.remember_file_id(coin, s["currency"], days, s["tz"], watermark, res.photo[-1].file_id)
        count("charts")
    except ApiTelegramException as e:
        if e.error_code == 403:
            db.mark_blocked(chat_id)
        elif "not modified" not in str(e).lower():
            raise


def reward_referrer(referrer: int, new_user) -> None:
    try:
        db.game_add_points(referrer, social.REF_BONUS)
        st = db.get_state(referrer)
        if st is not None:
            send(referrer, social.joined_text(st.settings["lang"], getattr(new_user, "first_name", None)))
        count("referrals")
    except Exception:
        logger.exception("referral reward failed for %s", referrer)


def handle_start(message) -> None:
    chat_id = message.chat.id
    payload = (message.text or "").partition(" ")[2].strip()
    ref, coin_id = social.parse_payload(payload) if payload else (None, None)
    is_new = not db.user_exists(chat_id)
    # переход по ссылке на монету не должен молча включать рассылку тому, кто её выключил
    state = db.ensure_user(chat_id, message.from_user, subscribe=is_new or not coin_id)
    s = state.settings
    if is_new:  # онбординг: язык (автоматически, если можем) -> профиль -> часовой пояс
        count("new_users")
        if ref and db.set_referrer(chat_id, ref):
            reward_referrer(ref, message.from_user)
        lang = social.detect_lang(getattr(message.from_user, "language_code", None))
        if lang:
            s = db.save_settings(chat_id, {"lang": lang}).settings
        if coin_id:
            show_card(chat_id, s, coin_id)
        if lang:
            send(chat_id, profile_text(lang), markup=profile_markup(lang, lang_btn=True))
        else:
            send(chat_id, "🌍 <b>Choose your language · Выберите язык</b>", markup=lang_picker_markup())
        return
    if coin_id and show_card(chat_id, s, coin_id):
        return
    t = T[s["lang"]]
    send(chat_id, t["start"].format(summary=summary(s)), markup=main_keyboard(s["lang"]))
    try:
        send(chat_id, prices_text(s, chat_id), markup=settings_markup(s["lang"], share=True))
    except Exception:
        logger.exception("start: prices failed for %s", chat_id)
        send(chat_id, t["err"])


def handle_top(message) -> None:
    s = user(message)
    try:
        text = prices_text(s, message.chat.id) or T[s["lang"]]["err"]
    except Exception:
        logger.exception("top: prices failed for %s", message.chat.id)
        text = T[s["lang"]]["err"]
    send(message.chat.id, text, markup=settings_markup(s["lang"], share=True))


def handle_settings(message) -> None:
    s = user(message)
    t = T[s["lang"]]
    if is_group(message.chat.id):  # мини-приложение в группах недоступно
        send(message.chat.id, t["group_settings"])
        return
    # settings_markup всегда содержит кнопку игры, поэтому проверяем сам WEBAPP_URL
    if config.WEBAPP_URL:
        send(message.chat.id, t["settings"], markup=settings_markup(s["lang"]))
    else:
        send(message.chat.id, t["no_webapp"])


def handle_profile(message) -> None:
    s = user(message, touch=False)
    send(message.chat.id, profile_text(s["lang"]), markup=profile_markup(s["lang"]))


def handle_game(message) -> None:
    s = user(message, touch=False)
    try:
        text, kb = game.new_card(s["lang"])
    except Exception:
        logger.exception("game card failed")
        send(message.chat.id, T[s["lang"]]["err"])
        return
    send(message.chat.id, text, markup=kb)


def handle_leaderboard(message) -> None:
    s = user(message, touch=False)
    text, kb = game.leaderboard(s["lang"], message.chat.id, "week")
    send(message.chat.id, text, markup=kb)


def handle_stop(message) -> None:
    s = user(message, touch=False)
    db.set_subscribed(message.chat.id, False)
    send(message.chat.id, T[s["lang"]]["stop"], markup=settings_markup(s["lang"]))


def handle_delete(message) -> None:
    s = user(message, touch=False)
    t = T[s["lang"]]
    if (message.text or "").strip().lower().endswith("confirm"):
        db.delete_user(message.chat.id)
        tools.pop_pending(message.chat.id)
        send(message.chat.id, t["deleted"], markup=types.ReplyKeyboardRemove())
    else:
        send(message.chat.id, t["delete_hint"])


def handle_help(message) -> None:
    s = user(message, touch=False)
    send(message.chat.id, T[s["lang"]]["help"].format(bot=BOT_USERNAME or "bot"),
         markup=main_keyboard(s["lang"]))


def _args(message) -> str:
    return (message.text or "").partition(" ")[2].strip()


def handle_price(message) -> None:
    s = user(message)
    tt = tools.TT[s["lang"]]
    q = _args(message)
    if not q:
        send(message.chat.id, tt["price_usage"])
        return
    coin = tools.resolve(q)
    if coin is None or not show_card(message.chat.id, s, coin["id"]):
        send(message.chat.id, tt["not_found"].format(q=html.escape(q[:40])))


def handle_chart(message) -> None:
    """/chart BTC [24h|7d|30d]"""
    s = user(message)
    parts = _args(message).split()
    if not parts:
        send(message.chat.id, chart.CT[s["lang"]]["usage"])
        return
    days = chart.parse_period(parts[-1]) if len(parts) > 1 else None
    name = " ".join(parts[:-1] if days else parts)
    days = days or 1
    coin = tools.resolve(name)
    if coin is None:
        send(message.chat.id, tools.TT[s["lang"]]["not_found"].format(q=html.escape(name[:40])))
        return
    send_chart(message.chat.id, s, coin["id"], days)


def handle_alerts(message) -> None:
    s = user(message)
    text, kb = tools.alerts_view(message.chat.id, s)
    send(message.chat.id, text, markup=kb)


def handle_alert(message) -> None:
    """/alert BTC 100000 — сразу создать; /alert BTC — выбрать уровень; /alert — список."""
    s = user(message)
    tt = tools.TT[s["lang"]]
    parts = _args(message).split()
    if not parts:
        handle_alerts(message)
        return
    target = tools.parse_number("".join(parts[1:])) if len(parts) > 1 else None
    coin = tools.resolve(parts[0])
    if coin is None:
        send(message.chat.id, tt["not_found"].format(q=html.escape(parts[0][:40])) + "\n\n" + tt["usage_alert"])
        return
    if len(parts) > 1 and target is None:
        send(message.chat.id, tt["bad_number"].format(ex=tools._example(coin.get("current_price"))))
        return
    if target is None:
        menu = tools.alert_menu(s, coin["id"])
        if menu:
            send(message.chat.id, menu[0], markup=menu[1])
        return
    send(message.chat.id, tools.add_alert(message.chat.id, s, coin["id"], target=target))


def handle_portfolio(message) -> None:
    s = user(message)
    try:
        text, kb = tools.portfolio_view(message.chat.id, s)
    except Exception:
        logger.exception("portfolio failed for %s", message.chat.id)
        text, kb = T[s["lang"]]["err"], None
    send(message.chat.id, text, markup=kb)


def _parse_amount(text: str):
    t = (text or "").strip()
    return 0.0 if re.fullmatch(r"0+([.,]0*)?", t) else tools.parse_number(t)


def _set_holding_from_text(chat_id: int, s: dict, text: str) -> None:
    """'BTC 0.5' -> сохранить; ошибки — с подсказкой."""
    tt = tools.TT[s["lang"]]
    parts = text.split()
    if len(parts) < 2:
        send(chat_id, tt["pf_usage"])
        return
    amount = _parse_amount(parts[-1])
    coin = tools.resolve(" ".join(parts[:-1]))
    if coin is None:
        send(chat_id, tt["not_found"].format(q=html.escape(" ".join(parts[:-1])[:40])))
    elif amount is None:
        send(chat_id, tt["bad_number"].format(ex="0.5"))
    else:
        send(chat_id, tools.set_holding(chat_id, s, coin["id"], amount))


def handle_add(message) -> None:
    s = user(message)
    _set_holding_from_text(message.chat.id, s, _args(message))


def handle_invite(message) -> None:
    s = user(message)
    text, kb = social.invite_view(s["lang"], message.chat.id, BOT_USERNAME,
                                  db.referral_count(message.chat.id), INLINE_OK)
    send(message.chat.id, text, markup=kb)


def handle_cancel(message) -> None:
    s = user(message, touch=False)
    tools.pop_pending(message.chat.id)
    send(message.chat.id, tools.TT[s["lang"]]["cancelled"], markup=main_keyboard(s["lang"]))


def handle_text(message) -> None:
    """Любой другой текст: ответ на вопрос (цена/количество) или поиск монеты по тикеру."""
    s = user(message)
    chat_id, text = message.chat.id, message.text.strip()
    tt = tools.TT[s["lang"]]
    pending = tools.pop_pending(chat_id)
    if pending:
        kind, coin_id = pending
        if kind == "alert":
            target = tools.parse_number(text)
            if target is None:
                tools.set_pending(chat_id, kind, coin_id)  # ждём ещё одну попытку
                q, placeholder = tools.ask_price_text(s, coin_id)
                ask(chat_id, tt["bad_number"].format(ex=tools._example(
                    (tools._coin_in(s["currency"], coin_id) or {}).get("current_price"))), placeholder)
            else:
                send(chat_id, tools.add_alert(chat_id, s, coin_id, target=target))
            return
        if kind == "pf":
            amount = _parse_amount(text)
            if amount is None:
                tools.set_pending(chat_id, kind, coin_id)
                ask(chat_id, tt["bad_number"].format(ex="0.5"), tt["placeholder_amount"])
            else:
                send(chat_id, tools.set_holding(chat_id, s, coin_id, amount))
            return
        if kind == "pfadd":
            _set_holding_from_text(chat_id, s, text)
            return
    coin = tools.resolve(text)
    if coin is not None and show_card(chat_id, s, coin["id"]):
        return
    if len(text) <= 24 and len(text.split()) <= 2:
        send(chat_id, tt["not_found"].format(q=html.escape(text)))
    else:
        send(chat_id, tt["unknown"], markup=main_keyboard(s["lang"]))


def guarded(handler):
    """Любая ошибка в обработчике: в лог (и алерт админу), пользователю — ничего не ломаем.
    Заодно защита от флуда."""
    def wrapper(message):
        try:
            if flooded(message.chat.id):
                return
            handler(message)
        except Exception:
            logger.exception("Handler %s failed (chat %s)", handler.__name__, message.chat.id)
    wrapper.__name__ = handler.__name__
    return wrapper


for _cmds, _h in (
    (["start"], handle_start), (["top"], handle_top), (["settings"], handle_settings),
    (["stop"], handle_stop), (["delete"], handle_delete), (["profile"], handle_profile),
    (["game"], handle_game), (["leaderboard"], handle_leaderboard), (["help"], handle_help),
    (["price", "p"], handle_price), (["chart", "c"], handle_chart), (["alerts"], handle_alerts), (["alert"], handle_alert),
    (["portfolio", "pf"], handle_portfolio), (["add"], handle_add), (["invite", "ref"], handle_invite),
    (["cancel"], handle_cancel),
):
    bot.message_handler(commands=_cmds)(guarded(_h))


def _private_text_in(m, words: set) -> bool:
    return m.chat.type == "private" and bool(m.text) and m.text.strip().lower() in words


def _btn_words(key: str, *extra) -> set:
    return set(extra) | {T[x][key].lower() for x in T}


START_WORDS = {"start", "старт"}
TOP_WORDS = _btn_words("btn_top", "top", "топ")
SETTINGS_WORDS = _btn_words("btn_settings", "settings", "настройки")
GAME_WORDS = _btn_words("btn_game", "game", "игра")
PF_WORDS = _btn_words("btn_pf", "portfolio", "портфель")
ALERTS_WORDS = _btn_words("btn_alerts", "alerts", "алерты")
INVITE_WORDS = _btn_words("btn_invite", "invite", "пригласить")

for _words, _h in ((START_WORDS, handle_start), (TOP_WORDS, handle_top), (SETTINGS_WORDS, handle_settings),
                   (GAME_WORDS, handle_game), (PF_WORDS, handle_portfolio), (ALERTS_WORDS, handle_alerts),
                   (INVITE_WORDS, handle_invite)):
    bot.message_handler(func=lambda m, w=_words: _private_text_in(m, w))(guarded(_h))

# последним: любой другой текст в личке (тикер монеты или ответ на вопрос бота)
# в группах — только ответы на вопросы бота (цена алерта, количество монет), остальной текст не трогаем
bot.message_handler(func=lambda m: bool(m.text) and not m.text.startswith("/")
                    and (m.chat.type == "private" or tools.has_pending(m.chat.id)),
                    content_types=["text"])(guarded(handle_text))


# ------------------------------------------------------------------
# Кнопки: онбординг (ob:*), игра (g:*), карточка монеты (c:*), алерты (pa:*), портфель (pf:*)
# ------------------------------------------------------------------
def edit(call, text: str, markup=None) -> None:
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=for_chat(call.message.chat.id, markup))
    except ApiTelegramException as e:
        if "not modified" not in str(e).lower():
            raise


def on_onboarding(call, parts: list, chat_id: int) -> None:
    action = parts[1]
    if action == "langs":
        edit(call, "🌍 <b>Choose your language · Выберите язык</b>", lang_picker_markup())
    elif action == "lang" and len(parts) > 2 and parts[2] in S.LANGS:
        state = db.save_settings(chat_id, {"lang": parts[2]})
        lang = state.settings["lang"]
        edit(call, profile_text(lang), profile_markup(lang))
    elif action == "prof" and len(parts) > 2:
        lang = db.get_state(chat_id).settings["lang"]
        name = parts[2]
        if name == "custom":
            edit(call, T[lang]["ob_custom"], settings_markup(lang))
            send(chat_id, T[lang]["tips"], markup=main_keyboard(lang))
            return
        if name not in S.PROFILES:
            return
        s = db.save_settings(chat_id, S.PROFILES[name]).settings
        edit(call, T[lang]["ob_done"].format(name=PROF[lang][name][0], summary=summary(s)))
        try:
            send(chat_id, prices_text(s, chat_id) or T[lang]["err"], markup=main_keyboard(lang))
        except Exception:
            logger.exception("onboarding: prices failed for %s", chat_id)
            send(chat_id, T[lang]["err"], markup=main_keyboard(lang))
        send(chat_id, T[lang]["ob_tz"].format(tz=s["tz"], off=utc_offset(s["tz"])), markup=tz_markup(lang))
    elif action == "tz":
        s = db.get_state(chat_id).settings
        edit(call, T[s["lang"]]["ob_tz_ok"].format(tz=s["tz"]))
        send(chat_id, T[s["lang"]]["tips"])


def _int(x, default=None):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def on_game(call, parts: list, chat_id: int, s: dict) -> None:
    lang, action = s["lang"], parts[1]
    if action == "new":  # новая карточка отдельным сообщением (не затираем отчёт)
        text, kb = game.new_card(lang)
        send(chat_id, text, markup=kb)
    elif action == "next":
        text, kb = game.new_card(lang, exclude=parts[2], horizon=_int(parts[3] if len(parts) > 3 else None,
                                                                         game.DEFAULT_H))
        edit(call, text, kb)
    elif action == "h" and len(parts) >= 4:  # смена срока прогноза на карточке
        text, kb = game.new_card(lang, coin_id=parts[2], horizon=_int(parts[3], game.DEFAULT_H))
        edit(call, text, kb)
    elif action == "p" and len(parts) >= 4:
        horizon = _int(parts[4], game.DEFAULT_H) if len(parts) > 4 else game.DEFAULT_H
        text, kb, ok = game.place(chat_id, lang, parts[2], parts[3], horizon, local_today(s))
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


def on_coin(call, parts: list, chat_id: int, s: dict):
    """Кнопки карточки монеты. Возвращает текст всплывающей подсказки или None."""
    action, coin_id = parts[1], parts[2] if len(parts) > 2 else ""
    tt = tools.TT[s["lang"]]
    if action == "r":  # обновить карточку на месте
        show_card(chat_id, s, coin_id, call=call)
    elif action == "o":  # открыть карточку новым сообщением (из алерта)
        show_card(chat_id, s, coin_id)
    elif action == "g":
        text, kb = game.new_card(s["lang"], coin_id=coin_id)
        send(chat_id, text, markup=kb)
    elif action == "fav":
        coins = list(s["custom_coins"])
        if coin_id in coins:
            coins.remove(coin_id)
            toast = tt["fav_removed"]
        elif len(coins) >= S.SPEC["custom_coins"]["max"]:
            return tt["fav_full"]
        else:
            coins.append(coin_id)
            toast = tt["fav_added"] if s["list_mode"] == "custom" else tt["fav_added_hint"]
        try:
            s = db.save_settings(chat_id, {"custom_coins": coins}).settings
        except ValueError:  # нельзя убрать последнюю монету в режиме «Мои монеты»
            return "⚠️"
        show_card(chat_id, s, coin_id, call=call)
        return toast
    return None


def on_price_alert(call, parts: list, chat_id: int, s: dict):
    action = parts[1]
    tt = tools.TT[s["lang"]]
    if action == "menu" and len(parts) > 2:
        menu = tools.alert_menu(s, parts[2])
        if menu:
            send(chat_id, menu[0], markup=menu[1])
    elif action == "add" and len(parts) > 3:
        pct = _int(parts[3])
        if pct is not None and abs(pct) in tools.LEVELS:
            edit(call, tools.add_alert(chat_id, s, parts[2], pct=pct))
    elif action == "ask" and len(parts) > 2:
        text, placeholder = tools.ask_price_text(s, parts[2])
        if text:
            tools.set_pending(chat_id, "alert", parts[2])
            ask(chat_id, text, placeholder)
    elif action == "del" and len(parts) > 2:
        db.alert_delete(chat_id, _int(parts[2], 0))
        text, kb = tools.alerts_view(chat_id, s)
        edit(call, text, kb)
        return tt["deleted"]
    return None


def on_portfolio(call, parts: list, chat_id: int, s: dict):
    action = parts[1]
    tt = tools.TT[s["lang"]]
    if action == "ask" and len(parts) > 2:
        text = tools.ask_amount_text(s, parts[2])
        if text:
            tools.set_pending(chat_id, "pf", parts[2])
            ask(chat_id, text, tt["placeholder_amount"])
    elif action == "add":
        tools.set_pending(chat_id, "pfadd")
        ask(chat_id, tt["pf_add_ask"], "BTC 0.5")
    elif action == "view":
        text, kb = tools.portfolio_view(chat_id, s)
        edit(call, text, kb)
    return None


def on_chart(call, parts: list, chat_id: int, s: dict):
    if len(parts) < 4:
        return None
    days = _int(parts[3], 1)
    if parts[1] == "o":
        send_chart(chat_id, s, parts[2], days)
    elif parts[1] == "p":
        send_chart(chat_id, s, parts[2], days, call=call)
    return None


CALLBACK_PREFIXES = ("ob", "g", "c", "pa", "pf", "ch")


@bot.callback_query_handler(func=lambda c: bool(c.data) and c.data.split(":")[0] in CALLBACK_PREFIXES)
def on_callback(call):
    chat_id = call.message.chat.id
    toast = None
    try:
        if flooded(chat_id):
            return
        s = db.ensure_user(chat_id, call.from_user, touch=False).settings
        parts = call.data.split(":")
        kind = parts[0]
        if kind == "ob":
            on_onboarding(call, parts, chat_id)
        elif kind == "g":
            on_game(call, parts, chat_id, s)
        elif kind == "c":
            toast = on_coin(call, parts, chat_id, s)
        elif kind == "pa":
            toast = on_price_alert(call, parts, chat_id, s)
        elif kind == "pf":
            toast = on_portfolio(call, parts, chat_id, s)
        elif kind == "ch":
            toast = on_chart(call, parts, chat_id, s)
    except Exception:
        logger.exception("Callback %s failed (chat %s)", call.data, chat_id)
    finally:
        try:
            bot.answer_callback_query(call.id, text=toast)
        except Exception:
            pass


# ------------------------------------------------------------------
# Inline-режим: @bot btc в любом чате — карточка монеты с кнопкой «Открыть бота» (реферальной)
# ------------------------------------------------------------------
@bot.inline_handler(func=lambda q: True)
def on_inline(query):
    try:
        st = db.get_state(query.from_user.id)
        if st is not None:
            lang, cur = st.settings["lang"], st.settings["currency"]
        else:
            lang, cur = social.detect_lang(query.from_user.language_code) or "en", "usd"
        results = social.inline_results(query.query[:40], lang, cur, BOT_USERNAME, query.from_user.id)
        bot.answer_inline_query(query.id, results, cache_time=30, is_personal=True)
        count("inline_queries")
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        # разовый обрыв связи с Telegram: пользователь просто повторит запрос, админа не дёргаем
        logger.warning("Inline query: network error: %s", e)
    except ApiTelegramException as e:
        if "query is too old" in str(e).lower():  # ответили позже 10 секунд — не страшно
            logger.warning("Inline query expired")
        else:
            logger.exception("Inline query failed")
    except Exception:
        logger.exception("Inline query failed")


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
    with contextlib.nullcontext(sender) as ex:  # общий пул: не закрываем его после рассылки
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
UI_READY = False  # меню команд и описание бота выставлены в Telegram


def setup_telegram_ui() -> None:
    global UI_READY
    try:
        for lang, names in CMD_DESC.items():
            code = None if lang == "en" else lang
            cmds = [types.BotCommand(c, d) for c, d in zip(CMD_ORDER, names)]
            bot.set_my_commands(cmds, language_code=code)
            # «Что умеет этот бот?» до нажатия Start и короткое описание в профиле бота
            bot.set_my_description(help_texts.DESCRIPTION[lang], language_code=code)
            bot.set_my_short_description(help_texts.SHORT_DESCRIPTION[lang], language_code=code)
        if config.WEBAPP_URL:
            bot.set_chat_menu_button(menu_button=types.MenuButtonWebApp(
                type="web_app", text="⚙️ Settings", web_app=types.WebAppInfo(config.WEBAPP_URL)))
        else:
            logger.warning("WEBAPP_URL not set: settings button is disabled")
        UI_READY = True
    except Exception as e:
        # например, бот стартовал раньше, чем появился интернет: повторим из heartbeat
        logger.warning("Failed to configure Telegram UI (will retry): %s", e)


def load_identity() -> None:
    """Имя бота (для реферальных ссылок) и включён ли inline-режим. Повторяем при сетевых сбоях."""
    global BOT_USERNAME, INLINE_OK
    for attempt in range(3):
        try:
            me = bot.get_me()
            BOT_USERNAME, INLINE_OK = me.username, bool(me.supports_inline_queries)
            if not INLINE_OK:
                logger.warning("Inline mode is off: enable it in @BotFather -> /setinline "
                               "to let users share coin cards in any chat")
            return
        except Exception as e:
            logger.warning("get_me failed (%s), retrying", e)
            time.sleep(3 * (attempt + 1))
    logger.warning("Could not load bot identity yet: will retry every minute")


def shutdown(signum, frame) -> None:
    logger.info("Signal %s received, shutting down", signum)
    stop.set()
    bot.stop_polling()


def main() -> None:
    db.init_db()
    if config.USER_CHAT_IDS:
        db.seed_users(config.USER_CHAT_IDS)
    load_identity()
    setup_telegram_ui()

    threads = [
        threading.Thread(target=dispatcher_loop, name="dispatcher"),
        threading.Thread(target=prepare_loop, name="prepare"),
        threading.Thread(target=heartbeat_loop, name="heartbeat"),
        threading.Thread(target=moves_loop, name="moves"),
        threading.Thread(target=weekly_loop, name="weekly"),
        threading.Thread(target=game_loop, name="game"),
        threading.Thread(target=price_alerts_loop, name="price_alerts"),
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
            allowed_updates=["message", "callback_query", "inline_query"],
        )
    finally:
        stop.set()
        try:
            db.wake_dispatcher()  # будим спящий диспетчер, чтобы он сразу завершился
        except Exception:
            pass
        for th in threads:
            th.join(timeout=20)
        alerts.notify("⏹ Бот остановлен", key="stop", cooldown=0)
        alerts.flush()
        sender.shutdown(wait=False, cancel_futures=True)
        db.pool.close()  # иначе при выходе psycopg_pool падает в __del__ (PythonFinalizationError)


if __name__ == "__main__":
    main()
