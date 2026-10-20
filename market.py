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

import alerts
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


def keycap(i: int) -> str:
    """1 -> 1️⃣, 10 -> 🔟, 15 -> 1️⃣5️⃣"""
    if i == 10:
        return "🔟"
    return "".join(d + "\ufe0f\u20e3" for d in str(i))


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
        line = f"{keycap(i)} {emoji}<b>{html.escape(sym)}</b>: {fmt_price(c.get('current_price'), s['currency'])}"
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


FALLBACK_FACTS = {
    "ru": [
        "Генезис-блок Bitcoin (3 января 2009) содержит заголовок газеты The Times о втором спасении банков.",
        "22 мая 2010 года программист заплатил 10 000 BTC за две пиццы — первая известная покупка за биткоин.",
        "Эмиссия биткоина ограничена 21 миллионом монет, а награда майнерам делится пополам каждые 210 000 блоков (примерно раз в четыре года).",
        "Ethereum запущен 30 июля 2015 года, а в сентябре 2022 перешёл на Proof-of-Stake (The Merge), сократив энергопотребление сети более чем на 99%.",
        "Белая книга Bitcoin опубликована Сатоши Накамото 31 октября 2008 года и занимает всего 9 страниц.",
        "Минимальная единица биткоина называется сатоши — это 0,00000001 BTC.",
        "Биржа Mt. Gox обанкротилась в 2014 году после потери около 850 000 BTC — одно из крупнейших событий в истории рынка.",
        "Последний на данный момент халвинг Bitcoin произошёл в апреле 2024 года: награда за блок уменьшилась вдвое.",
        "Смарт-контракт — это программа в блокчейне, которая исполняется автоматически при выполнении заданных условий, без посредника.",
        "Блокчейн назван по структуре данных: блоки связаны цепочкой хэшей, поэтому изменить старый блок, не изменив все последующие, практически невозможно.",
    ],
    "en": [
        "Bitcoin's genesis block (Jan 3, 2009) contains a headline from The Times about a second bank bailout.",
        "On May 22, 2010 a programmer paid 10,000 BTC for two pizzas — the first known purchase made with bitcoin.",
        "Bitcoin supply is capped at 21 million coins, and the miner reward halves every 210,000 blocks (roughly every four years).",
        "Ethereum launched on July 30, 2015, and in September 2022 it switched to Proof-of-Stake (The Merge), cutting its energy use by more than 99%.",
        "The Bitcoin whitepaper was published by Satoshi Nakamoto on October 31, 2008 and is only 9 pages long.",
        "The smallest unit of bitcoin is called a satoshi: 0.00000001 BTC.",
        "The Mt. Gox exchange went bankrupt in 2014 after losing about 850,000 BTC — one of the biggest events in market history.",
        "The most recent Bitcoin halving happened in April 2024: the block reward was cut in half.",
        "A smart contract is a program on a blockchain that runs automatically once preset conditions are met, with no intermediary.",
        "A blockchain is named after its data structure: blocks are linked by a chain of hashes, so altering an old block without changing all later ones is practically impossible.",
    ],
}

_gemini_clients: dict = {}
_cooldown: dict = {}  # (индекс ключа, модель) -> время, до которого пропускаем (лимит 429)
_rr = {"i": 0}


def _client(idx: int):
    from google import genai
    from google.genai import types

    if idx not in _gemini_clients:
        _gemini_clients[idx] = genai.Client(
            api_key=config.GEMINI_KEYS[idx], http_options=types.HttpOptions(timeout=30000))
    return _gemini_clients[idx]


def _generate_ai(lang: str):
    """Пробует все ключи и модели по очереди. Возвращает текст или None."""
    keys = config.GEMINI_KEYS
    if not keys:
        logger.warning("No Gemini API keys configured")
        return None
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
    gen_config = types.GenerateContentConfig(temperature=0.8)

    deadline = time.time() + 90
    start = _rr["i"] % len(keys)
    order = [(start + k) % len(keys) for k in range(len(keys))]
    for idx in order:
        for model in config.GEMINI_MODELS:
            if time.time() > deadline:
                break
            if _cooldown.get((idx, model), 0) > time.time():
                continue
            for attempt in range(2):
                try:
                    resp = _client(idx).models.generate_content(
                        model=model, contents=prompt, config=gen_config)
                    text = (resp.text or "").strip()
                    if not text:
                        raise ValueError("empty response")
                    _rr["i"] = idx + 1  # следующий запрос начнём со следующего ключа
                    return f"{LABELS[lang]['ai']}\n{to_telegram_html(text)}"
                except Exception as e:
                    msg = str(e).replace(keys[idx], "***")
                    logger.warning("Gemini key#%d %s failed: %s", idx + 1, model, msg[:200])
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                        _cooldown[(idx, model)] = time.time() + 600  # лимит: пропускаем 10 минут
                        break
                    transient = any(x in msg for x in ("500", "503", "504", "UNAVAILABLE",
                                                        "overloaded", "timed out", "Timeout"))
                    if transient and attempt == 0 and time.time() < deadline:
                        time.sleep(3)
                        continue
                    break
    logger.warning("All Gemini keys/models failed (lang=%s)", lang)
    alerts.notify(
        "⚠️ Gemini недоступен (все ключи/модели). Пользователям отдаётся прошлая аналитика "
        "или запасной текст. Причины — в логах: journalctl -u cryptobot | grep Gemini",
        key="gemini_fail", cooldown=3600)
    return None


def fallback_ai_text(lang: str) -> str:
    """Запасная аналитика без Gemini: реальное изменение рынка + проверенный факт."""
    entry = _mcache.get("usd")
    parts = []
    if entry:
        ch = [c.get("price_change_percentage_24h_in_currency") for c in entry["data"][:10]]
        ch = [c for c in ch if c is not None]
        if ch:
            avg = sum(ch) / len(ch)
            parts.append(f"Рынок (топ-10) за сутки в среднем {avg:+.2f}%." if lang == "ru"
                         else f"The market (top 10) is {avg:+.2f}% on average over 24h.")
    facts = FALLBACK_FACTS[lang]
    fact = facts[datetime.now(timezone.utc).hour % len(facts)]
    parts.append(("💡 Факт: " if lang == "ru" else "💡 Fact: ") + html.escape(fact))
    return f"{LABELS[lang]['ai']}\n" + "\n".join(parts)


_ai_cache: dict = {}
_ai_fail_until: dict = {}
_ai_warming: set = set()


def _warm_async(lang: str) -> None:
    if lang in _ai_warming:
        return
    _ai_warming.add(lang)

    def run():
        try:
            get_ai_text(lang)
        finally:
            _ai_warming.discard(lang)

    threading.Thread(target=run, daemon=True, name=f"ai-warm-{lang}").start()


def get_ai_text(lang: str, force: bool = False, cached_only: bool = False) -> str:
    """Аналитика всегда возвращает текст. Генерируется раз в час (один запрос на язык) и
    кэшируется. Цепочка: свежий кэш -> Gemini (все ключи/модели) -> прошлая аналитика (до
    AI_STALE_HOURS ч) -> запасной текст. cached_only=True никогда не ждёт Gemini."""
    fresh_age = config.AI_CACHE_MIN * 60
    stale_age = config.AI_STALE_HOURS * 3600
    entry = _ai_cache.get(lang)
    age = time.time() - entry[0] if entry else None

    if cached_only:
        if entry is None:
            _warm_async(lang)  # кэша ещё нет (свежий запуск): греем в фоне
        elif age < stale_age:
            return entry[1]
        return fallback_ai_text(lang)

    if entry and not force and age < fresh_age:
        return entry[1]
    with _lock_for("ai:" + lang):
        entry = _ai_cache.get(lang)
        if entry and not force and time.time() - entry[0] < fresh_age:
            return entry[1]
        if force or time.time() >= _ai_fail_until.get(lang, 0):
            text = _generate_ai(lang)
            if text:
                _ai_cache[lang] = (time.time(), text)
                return text
            _ai_fail_until[lang] = time.time() + 120  # не долбим Gemini при сбое
        if entry and time.time() - entry[0] < stale_age:
            return entry[1]
        return fallback_ai_text(lang)


def cache_info() -> dict:
    now = time.time()
    return {
        "markets": {k: int(now - v["ts"]) for k, v in _mcache.items()},
        "ai": {k: int(now - v[0]) for k, v in _ai_cache.items()},
    }


# ------------------------------------------------------------------
# Сборка сообщения по настройкам пользователя
# ------------------------------------------------------------------
def compose(s: dict, want_report: bool, want_analytics: bool, now: datetime = None,
            ai_cached_only: bool = False):
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
        ai = get_ai_text(s["lang"], cached_only=ai_cached_only)
        if ai:
            parts.append(ai)
    if not parts:
        return None
    header = lab["hdr_market" if has_report else "hdr_ai"].format(time=local)
    return header + "\n\n" + "\n\n".join(parts)
