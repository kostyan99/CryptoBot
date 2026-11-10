"""Рост аудитории: реферальные ссылки, inline-режим (@bot btc в любом чате), язык по профилю Telegram."""
import html
import re
from urllib.parse import quote

from telebot import types

import market as M
import tools

class ShareButton(types.InlineKeyboardButton):
    """Кнопка «Поделиться» (выбор чата + inline-запрос). pyTelegramBotAPI выкидывает пустой
    switch_inline_query при сериализации, и Telegram отклоняет всё сообщение
    («Text buttons are not allowed»), поэтому поле пишем всегда, даже пустое."""

    def __init__(self, text: str, query: str = ""):
        super().__init__(text, switch_inline_query=query)
        self.share_query = query

    def to_dict(self):
        d = super().to_dict()
        d["switch_inline_query"] = self.share_query
        return d


REF_BONUS = 50  # баллов игры за каждого приглашённого друга

# language_code Telegram -> язык бота. Для остальных показываем выбор языка.
LANG_FROM_CODE = {"en": "en", "ru": "ru", "be": "ru", "kk": "ru", "ky": "ru", "uz": "ru", "tg": "ru",
                  "fr": "fr", "es": "es", "de": "de", "uk": "uk"}

ST = {
    "en": {
        "invite": "🎁 <b>Invite friends</b>\n\nFor every friend who joins via your link you get <b>+{bonus}</b> game points 🎯\n\n"
                  "Your link:\n{link}\n\n👥 Friends invited: <b>{n}</b>",
        "btn_send": "📤 Send to friends", "btn_inline": "💬 Share a coin card",
        "share_text": "Crypto prices, AI market analytics, price alerts and a prediction game — right in Telegram 🚀",
        "joined": "🎉 Your friend <b>{name}</b> joined via your link! +{bonus} game points 🎯",
        "friend": "a friend", "open": "🤖 Open the bot", "overview": "📊 Crypto market now",
        "overview_desc": "Top 10 coins with 24h change", "no_link": "⚠️ Invite links are temporarily unavailable.",
    },
    "ru": {
        "invite": "🎁 <b>Пригласите друзей</b>\n\nЗа каждого друга, который придёт по вашей ссылке, вы получите <b>+{bonus}</b> баллов в игре 🎯\n\n"
                  "Ваша ссылка:\n{link}\n\n👥 Приглашено друзей: <b>{n}</b>",
        "btn_send": "📤 Отправить друзьям", "btn_inline": "💬 Поделиться монетой",
        "share_text": "Курсы крипты, AI-аналитика рынка, ценовые алерты и игра-прогноз — прямо в Telegram 🚀",
        "joined": "🎉 Ваш друг <b>{name}</b> пришёл по вашей ссылке! +{bonus} баллов в игре 🎯",
        "friend": "друг", "open": "🤖 Открыть бота", "overview": "📊 Крипторынок сейчас",
        "overview_desc": "Топ-10 монет и изменение за 24ч", "no_link": "⚠️ Пригласительные ссылки временно недоступны.",
    },
    "fr": {
        "invite": "🎁 <b>Invitez vos amis</b>\n\nPour chaque ami qui rejoint via votre lien, vous gagnez <b>+{bonus}</b> points de jeu 🎯\n\n"
                  "Votre lien :\n{link}\n\n👥 Amis invités : <b>{n}</b>",
        "btn_send": "📤 Envoyer à des amis", "btn_inline": "💬 Partager une crypto",
        "share_text": "Cours crypto, analyses IA du marché, alertes de prix et jeu de pronostics — directement dans Telegram 🚀",
        "joined": "🎉 Votre ami <b>{name}</b> a rejoint via votre lien ! +{bonus} points de jeu 🎯",
        "friend": "un ami", "open": "🤖 Ouvrir le bot", "overview": "📊 Le marché crypto maintenant",
        "overview_desc": "Top 10 et variation sur 24 h", "no_link": "⚠️ Les liens d’invitation sont temporairement indisponibles.",
    },
    "es": {
        "invite": "🎁 <b>Invita a tus amigos</b>\n\nPor cada amigo que se una con tu enlace recibes <b>+{bonus}</b> puntos en el juego 🎯\n\n"
                  "Tu enlace:\n{link}\n\n👥 Amigos invitados: <b>{n}</b>",
        "btn_send": "📤 Enviar a amigos", "btn_inline": "💬 Compartir una moneda",
        "share_text": "Precios cripto, análisis del mercado con IA, alertas de precio y un juego de predicciones — en Telegram 🚀",
        "joined": "🎉 ¡Tu amigo <b>{name}</b> se unió con tu enlace! +{bonus} puntos en el juego 🎯",
        "friend": "un amigo", "open": "🤖 Abrir el bot", "overview": "📊 El mercado cripto ahora",
        "overview_desc": "Top 10 y variación en 24 h", "no_link": "⚠️ Los enlaces de invitación no están disponibles temporalmente.",
    },
    "de": {
        "invite": "🎁 <b>Freunde einladen</b>\n\nFür jeden Freund, der über Ihren Link beitritt, erhalten Sie <b>+{bonus}</b> Spielpunkte 🎯\n\n"
                  "Ihr Link:\n{link}\n\n👥 Eingeladene Freunde: <b>{n}</b>",
        "btn_send": "📤 An Freunde senden", "btn_inline": "💬 Coin teilen",
        "share_text": "Krypto-Kurse, KI-Marktanalyse, Preisalarme und ein Tippspiel — direkt in Telegram 🚀",
        "joined": "🎉 Ihr Freund <b>{name}</b> ist über Ihren Link beigetreten! +{bonus} Spielpunkte 🎯",
        "friend": "ein Freund", "open": "🤖 Bot öffnen", "overview": "📊 Kryptomarkt jetzt",
        "overview_desc": "Top 10 mit 24-Std.-Änderung", "no_link": "⚠️ Einladungslinks sind vorübergehend nicht verfügbar.",
    },
    "uk": {
        "invite": "🎁 <b>Запросіть друзів</b>\n\nЗа кожного друга, який прийде за вашим посиланням, ви отримаєте <b>+{bonus}</b> балів у грі 🎯\n\n"
                  "Ваше посилання:\n{link}\n\n👥 Запрошено друзів: <b>{n}</b>",
        "btn_send": "📤 Надіслати друзям", "btn_inline": "💬 Поділитися монетою",
        "share_text": "Курси крипти, AI-аналітика ринку, цінові алерти та гра-прогноз — просто в Telegram 🚀",
        "joined": "🎉 Ваш друг <b>{name}</b> прийшов за вашим посиланням! +{bonus} балів у грі 🎯",
        "friend": "друг", "open": "🤖 Відкрити бота", "overview": "📊 Крипторинок зараз",
        "overview_desc": "Топ-10 монет і зміна за 24 год", "no_link": "⚠️ Запрошувальні посилання тимчасово недоступні.",
    },
}


def detect_lang(code) -> str:
    """Язык бота по language_code пользователя или None (тогда показываем выбор)."""
    return LANG_FROM_CODE.get((code or "").split("-")[0].lower())


def ref_link(username: str, chat_id: int, coin_id: str = None) -> str:
    payload = f"r{chat_id}" + (f"__{coin_id}" if coin_id else "")
    return f"https://t.me/{username}?start={payload[:64]}"


def parse_payload(payload: str) -> tuple:
    """'r123__bitcoin' -> (123, 'bitcoin'); 'c__bitcoin' -> (None, 'bitcoin')."""
    ref, coin = None, None
    for part in (payload or "").split("__"):
        if re.fullmatch(r"r\d{1,20}", part):
            ref = int(part[1:])
        elif re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", part) and part != "c":
            coin = part
    return ref, coin


def invite_view(lang: str, chat_id: int, username: str, n: int, inline_ok: bool):
    st = ST[lang]
    if not username:
        return st["no_link"], None
    link = ref_link(username, chat_id)
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton(
        st["btn_send"], url=f"https://t.me/share/url?url={quote(link)}&text={quote(st['share_text'])}"))
    if inline_ok:
        kb.row(ShareButton(st["btn_inline"]))
    return st["invite"].format(bonus=REF_BONUS, link=html.escape(link), n=n), kb


def joined_text(lang: str, first_name) -> str:
    st = ST[lang]
    name = html.escape((first_name or "").strip()[:30]) or st["friend"]
    return st["joined"].format(name=name, bonus=REF_BONUS)


# ------------------------------------------------------------------
# Inline-режим
# ------------------------------------------------------------------
def _open_markup(lang: str, username: str, uid: int, coin_id: str = None):
    if not username:
        return None
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton(ST[lang]["open"], url=ref_link(username, uid, coin_id)))
    return kb


def _overview_text(data: list, lang: str, currency: str) -> str:
    lab = M.LABELS[lang]
    coins = M._pool(data)[:10]
    lines = [f"{M.keycap(i)} <b>{html.escape(c['symbol'].upper())}</b> {M.fmt_price(c.get('current_price'), currency)} "
             f"({M.fmt_pct(c.get('price_change_percentage_24h_in_currency'))})" for i, c in enumerate(coins, start=1)]
    mood = M.mood_line(data, lang)
    head = lab["top"].format(n=len(coins))
    return (f"<i>{mood}</i>\n\n" if mood else "") + head + "\n" + "\n".join(lines)


def inline_results(query: str, lang: str, currency: str, username: str, uid: int) -> list:
    data = M.get_markets(currency)
    results = []
    q = (query or "").strip()
    coins = tools.search(q, data, limit=8) if q else [c for c in M._pool(data)[:3]]
    if not q:
        results.append(types.InlineQueryResultArticle(
            id="overview", title=ST[lang]["overview"], description=ST[lang]["overview_desc"],
            input_message_content=types.InputTextMessageContent(
                _overview_text(data, lang, currency), parse_mode="HTML"),
            reply_markup=_open_markup(lang, username, uid)))
    for c in coins:
        sym = c["symbol"].upper()
        title = f"{sym} · {M.fmt_price(c.get('current_price'), currency)}"
        desc = f"{c.get('name', '')} · 24h {M.fmt_pct(c.get('price_change_percentage_24h_in_currency'))}"
        results.append(types.InlineQueryResultArticle(
            id=f"c:{c['id']}"[:64], title=title, description=desc,
            thumbnail_url=c.get("image") or None,
            input_message_content=types.InputTextMessageContent(
                tools.card_text(c, lang, currency), parse_mode="HTML"),
            reply_markup=_open_markup(lang, username, uid, c["id"])))
    return results
