"""Данные рынка (CoinGecko, кэш), новости, аналитика Gemini и сборка сообщения."""
import calendar
import html
import logging
import random
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import feedparser
import requests

import config

logger = logging.getLogger("market")

STABLES = {
    "USDT", "USDC", "DAI", "FDUSD", "USDE", "USDS", "PYUSD", "TUSD", "USDT0",
    "BUIDL", "USDTB", "BSC-USD", "FIGR_HELOC",
}
WRAPPED = {"STETH", "WSTETH", "WEETH", "WBTC", "WETH", "WBETH", "CBBTC"}

COIN_EMOJIS = {
    "BTC": "🟠", "ETH": "🔹", "SOL": "🟣", "TON": "💎", "PEPE": "🐸", "DOGE": "🐕",
    "XRP": "🪙", "BNB": "🟡", "ADA": "🔵", "AVAX": "🔴", "LINK": "🔗", "TRX": "🔴", "DOT": "🟣",
}

CURRENCY_FMT = {"usd": ("$", True), "eur": ("€", True), "uah": ("₴", True),
                "gbp": ("£", True), "pln": (" zł", False)}

NEWS_FEEDS = ["https://forklog.com/feed/", "https://cointelegraph.com/rss"]

FACT_TOPICS = {
    "ru": ["история биткоина", "устройство блокчейна", "смарт-контракты",
           "знаменитые взломы и уроки из них", "майнинг", "NFT и DAO",
           "Layer 2 и масштабирование", "история Ethereum", "мем-коины",
           "криптография в блокчейне", "халвинг", "стейблкоины и их риски"],
    "en": ["history of Bitcoin", "how blockchains work", "smart contracts",
           "famous hacks and their lessons", "mining", "NFTs and DAOs",
           "Layer 2 scaling", "history of Ethereum", "meme coins",
           "cryptography in blockchains", "halving", "stablecoins and their risks"],
}

LABELS = {
    "ru": {"hdr_market": "📊 <b>Обзор рынка на {time}</b>", "hdr_ai": "🧠 <b>Аналитика на {time}</b>",
           "top": "🏆 <b>Топ-{n} монет</b>", "gainers": "🚀 <b>Лидеры роста</b>",
           "losers": "🔻 <b>Лидеры падения</b>", "ai": "🧠 <b>Аналитика и факты:</b>"},
    "en": {"hdr_market": "📊 <b>Market overview, {time}</b>", "hdr_ai": "🧠 <b>Analytics, {time}</b>",
           "top": "🏆 <b>Top {n} coins</b>", "gainers": "🚀 <b>Top gainers</b>",
           "losers": "🔻 <b>Top losers</b>", "ai": "🧠 <b>Analytics & facts:</b>"},
}


# ------------------------------------------------------------------
# HTTP + кэш курсов
# ------------------------------------------------------------------
def fetch_json(url: str, retries: int = 4, timeout: int = 15):
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux aarch64)", "Accept": "application/json"}
    if config.COINGECKO_KEY and "coingecko.com" in url:
        headers["x-cg-demo-api-key"] = config.COINGECKO_KEY
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                logger.warning("429 from CoinGecko, sleeping %ss", wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.warning("Request error: %s", e)
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("CoinGecko: rate limited (429) after retries")


_mcache: dict = {}
_mlocks: dict = {}
_mlocks_guard = threading.Lock()


def _lock_for(name: str) -> threading.Lock:
    with _mlocks_guard:
        return _mlocks.setdefault(name, threading.Lock())


def get_markets(currency: str = "usd", max_age: float = None) -> list:
    """Топ-60 по капитализации в нужной валюте. Кэш на CACHE_TTL сек: тысячи запросов
    пользователей = один запрос к CoinGecko. Пока кто-то обновляет кэш, остальные
    получают предыдущие данные; при сбое отдаётся кэш не старше STALE_MAX_SEC."""
    max_age = config.CACHE_TTL if max_age is None else max_age
    entry = _mcache.get(currency)
    if entry and time.time() - entry["ts"] < max_age:
        return entry["data"]

    lock = _lock_for("m:" + currency)
    if not lock.acquire(blocking=(entry is None or max_age == 0)):
        return entry["data"]
    try:
        entry = _mcache.get(currency)
        if max_age > 0 and entry and time.time() - entry["ts"] < max_age:
            return entry["data"]
        url = (
            "https://api.coingecko.com/api/v3/coins/markets"
            f"?vs_currency={currency}&order=market_cap_desc&per_page=60&page=1"
            "&sparkline=false&price_change_percentage=24h,7d"
        )
        try:
            data = fetch_json(url)
            if not isinstance(data, list) or not data:
                raise ValueError("unexpected CoinGecko response")
        except Exception:
            if entry and time.time() - entry["ts"] < config.STALE_MAX_SEC:
                logger.warning("CoinGecko failed, serving stale cache (%s)", currency)
                return entry["data"]
            raise
        _mcache[currency] = {"ts": time.time(), "data": data}
        return data
    finally:
        lock.release()


# ------------------------------------------------------------------
# Форматирование
# ------------------------------------------------------------------
def fmt_price(price, currency: str) -> str:
    if price is None:
        return "—"
    sym, prefix = CURRENCY_FMT.get(currency, ("$", True))
    if price >= 1000:
        num = f"{price:,.2f}".replace(",", " ")
    elif price >= 1:
        num = f"{price:.2f}"
    elif price >= 0.01:
        num = f"{price:.4f}"
    elif price >= 0.0001:
        num = f"{price:.6f}"
    else:
        num = f"{price:.8f}"
    return f"{sym}{num}" if prefix else f"{num}{sym}"


def fmt_change(change) -> str:
    if change is None:
        return "⚪ —"
    if change > 0:
        return f"📈 +{change:.2f}%"
    if change < 0:
        return f"📉 {change:.2f}%"
    return "➡️ 0.00%"


def to_telegram_html(text: str) -> str:
    text = html.escape(text.strip(), quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.S)
    text = re.sub(r"^[\*\-]\s+", "• ", text, flags=re.M)
    return text.replace("`", "").replace("*", "")


def _change_key(period: str) -> str:
    return "price_change_percentage_7d_in_currency" if period == "7d" else \
        "price_change_percentage_24h_in_currency"


def pick_coins(data: list, s: dict) -> list:
    pool = [
        c for c in data
        if c["symbol"].upper() not in WRAPPED
        and (s["include_stables"] or c["symbol"].upper() not in STABLES)
    ]
    n, mode = s["coins_count"], s["list_mode"]
    if mode == "top":
        return pool[:n]
    key = _change_key(s["change_period"])
    ranked = sorted((c for c in pool if c.get(key) is not None),
                    key=lambda c: c[key], reverse=(mode == "gainers"))
    return ranked[:n]


def build_coin_block(data: list, s: dict) -> str:
    coins = pick_coins(data, s)
    if not coins:
        return ""
    lab = LABELS[s["lang"]]
    key = _change_key(s["change_period"])
    title = lab[s["list_mode"]].format(n=len(coins))
    if s["show_change"] or s["list_mode"] != "top":
        title += f" · {s['change_period']}"
    lines = []
    for i, c in enumerate(coins, start=1):
        sym = c["symbol"].upper()
        emoji = (COIN_EMOJIS.get(sym, "⚡️") + " ") if s["show_emoji"] else ""
        line = f"{i}. {emoji}<b>{html.escape(sym)}</b>: {fmt_price(c.get('current_price'), s['currency'])}"
        if s["show_change"]:
            line += f" ({fmt_change(c.get(key))})"
        lines.append(line)
    return title + "\n" + "\n".join(lines)


# ------------------------------------------------------------------
# Новости и Gemini
# ------------------------------------------------------------------
def get_recent_headlines(hours: int = 8, limit: int = 15) -> list:
    now_utc = datetime.now(timezone.utc)
    result, seen = [], set()
    for url in NEWS_FEEDS:
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            feed = feedparser.parse(r.content)
        except Exception as e:
            logger.warning("Feed %s unavailable: %s", url, e)
            continue
        for entry in feed.entries:
            parsed = getattr(entry, "published_parsed", None)
            if not parsed:
                continue
            published = datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc)
            title = entry.get("title", "").strip()
            if title and title not in seen and now_utc - published <= timedelta(hours=hours):
                seen.add(title)
                result.append(title)
    return result[:limit]


def _build_prompt(lang: str, trend: str, avg: float, headlines: list) -> str:
    topic = random.choice(FACT_TOPICS[lang])
    if lang == "ru":
        news = ("Заголовки за последние часы:\n- " + "\n- ".join(headlines)
                if headlines else "Новостей за последние часы нет.")
        return (
            "Ты дружелюбный крипто-эксперт, пишешь для Telegram на русском.\n"
            f"Рынок (топ-10) сейчас {trend}, в среднем {avg:+.2f}% за сутки.\n{news}\n\n"
            "ПРАВИЛО 1: если среди заголовков есть ВАЖНЫЕ события (взломы, законы, суды, ETF, "
            "крупные сдвиги), напиши аналитику на 2-3 предложения: что произошло и как это "
            "может повлиять на рынок. Не выдумывай того, чего нет в заголовках.\n"
            "ПРАВИЛО 2: если новостей нет или они неважные, начни ответ со слов "
            "'На рынке новостной штиль ⛵️' и расскажи ОДИН малоизвестный проверяемый факт "
            f"на тему «{topic}» (2-3 предложения). Не выдумывай цифры и даты.\n"
            "Без приветствий, без markdown-разметки, без советов покупать или продавать."
        )
    news = ("Recent headlines:\n- " + "\n- ".join(headlines)
            if headlines else "No notable news in the last hours.")
    return (
        "You are a friendly crypto expert writing for Telegram in English.\n"
        f"The market (top 10) is currently {trend}, {avg:+.2f}% on average over 24h.\n{news}\n\n"
        "RULE 1: if the headlines contain IMPORTANT events (hacks, laws, court cases, ETFs, big "
        "moves), write 2-3 sentences of analysis: what happened and how it may affect the market. "
        "Do not invent anything that is not in the headlines.\n"
        "RULE 2: if there is no news or it is unimportant, start with 'Quiet day on the news "
        f"front ⛵️' and share ONE little-known verifiable fact about '{topic}' (2-3 sentences). "
        "Do not invent numbers or dates.\n"
        "No greetings, no markdown, no buy/sell advice."
    )


def _generate_ai(lang: str):
    if not config.GEMINI_KEY:
        logger.warning("GEMINI_API_KEY not set")
        return None
    from google import genai
    from google.genai import types

    try:
        top = get_markets("usd")[:10]
    except Exception:
        top = []
    changes = [c.get("price_change_percentage_24h_in_currency") for c in top]
    changes = [c for c in changes if c is not None]
    avg = sum(changes) / len(changes) if changes else 0.0
    ru = lang == "ru"
    trend = (("растёт" if ru else "rising") if avg > 0.5
             else ("падает" if ru else "falling") if avg < -0.5
             else ("во флэте" if ru else "flat"))
    prompt = _build_prompt(lang, trend, avg, get_recent_headlines())

    client = genai.Client(api_key=config.GEMINI_KEY, http_options=types.HttpOptions(timeout=45000))
    gen_config = types.GenerateContentConfig(temperature=0.8)
    for model in config.GEMINI_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=gen_config)
            text = (resp.text or "").strip()
            if not text:
                raise ValueError("empty response")
            return f"{LABELS[lang]['ai']}\n{to_telegram_html(text)}"
        except Exception as e:
            logger.warning("Gemini model %s failed: %s", model, e)
    logger.error("All Gemini models failed (lang=%s)", lang)
    return None


_ai_cache: dict = {}


def get_ai_text(lang: str, force: bool = False):
    """Аналитика с кэшем (генерируется один раз на язык, а не на каждого пользователя)."""
    max_age = config.AI_CACHE_MIN * 60
    entry = _ai_cache.get(lang)
    if entry and not force and time.time() - entry[0] < max_age:
        return entry[1]
    with _lock_for("ai:" + lang):
        entry = _ai_cache.get(lang)
        if entry and not force and time.time() - entry[0] < max_age:
            return entry[1]
        text = _generate_ai(lang)
        if text:
            _ai_cache[lang] = (time.time(), text)
            return text
        if entry and time.time() - entry[0] < 3 * 3600:
            return entry[1]
        return None


def cache_info() -> dict:
    now = time.time()
    return {
        "markets": {k: int(now - v["ts"]) for k, v in _mcache.items()},
        "ai": {k: int(now - v[0]) for k, v in _ai_cache.items()},
    }


# ------------------------------------------------------------------
# Сборка сообщения по настройкам пользователя
# ------------------------------------------------------------------
def compose(s: dict, want_report: bool, want_analytics: bool, now: datetime = None):
    """Текст сообщения для пользователя или None, если показывать нечего."""
    now = now or datetime.now(timezone.utc)
    lab = LABELS[s["lang"]]
    local = now.astimezone(ZoneInfo(s["tz"])).strftime("%d.%m.%Y %H:%M")
    parts, has_report = [], False
    if want_report:
        block = build_coin_block(get_markets(s["currency"]), s)
        if block:
            parts.append(block)
            has_report = True
    if want_analytics:
        ai = get_ai_text(s["lang"])
        if ai:
            parts.append(ai)
    if not parts:
        return None
    header = lab["hdr_market" if has_report else "hdr_ai"].format(time=local)
    return header + "\n\n" + "\n\n".join(parts)
