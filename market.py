"""Данные рынка (CoinGecko, кэш), новости, Gemini (аналитика и факты), сборка сообщения."""
import calendar
import collections
import html
import json
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

# символ, ставится ли перед числом
CURRENCY_FMT = {"usd": ("$", True), "eur": ("€", True), "rub": (" ₽", False),
                "uah": (" ₴", False), "kzt": (" ₸", False)}

LANG_NAMES = {"ru": "Russian", "en": "English", "fr": "French", "es": "Spanish", "de": "German"}

NEWS_FEEDS = ["https://forklog.com/feed/", "https://cointelegraph.com/rss"]

FACT_TOPICS = [
    "history of Bitcoin", "how blockchains work", "smart contracts",
    "famous hacks and their lessons", "mining", "NFTs and DAOs", "Layer 2 scaling",
    "history of Ethereum", "meme coins", "cryptography in blockchains", "halving",
    "stablecoins and their risks", "crypto wallets and private keys",
    "proof of stake versus proof of work", "early crypto pioneers",
    "history of crypto exchanges", "decentralized finance (DeFi)",
]

LABELS = {
    "en": {"hdr_market": "📊 <b>Market overview, {time}</b>", "hdr_digest": "🧠 <b>Crypto digest, {time}</b>",
           "top": "🏆 <b>Top {n} coins</b>", "gainers": "🚀 <b>Top gainers</b>",
           "losers": "🔻 <b>Top losers</b>", "ai": "🧠 <b>Analytics:</b>", "fact": "💡 <b>Fun fact:</b>"},
    "ru": {"hdr_market": "📊 <b>Обзор рынка на {time}</b>", "hdr_digest": "🧠 <b>Крипто-дайджест на {time}</b>",
           "top": "🏆 <b>Топ-{n} монет</b>", "gainers": "🚀 <b>Лидеры роста</b>",
           "losers": "🔻 <b>Лидеры падения</b>", "ai": "🧠 <b>Аналитика:</b>", "fact": "💡 <b>Интересный факт:</b>"},
    "fr": {"hdr_market": "📊 <b>Aperçu du marché, {time}</b>", "hdr_digest": "🧠 <b>Digest crypto, {time}</b>",
           "top": "🏆 <b>Top {n} cryptos</b>", "gainers": "🚀 <b>Plus fortes hausses</b>",
           "losers": "🔻 <b>Plus fortes baisses</b>", "ai": "🧠 <b>Analyse :</b>", "fact": "💡 <b>Le saviez-vous ?</b>"},
    "es": {"hdr_market": "📊 <b>Resumen del mercado, {time}</b>", "hdr_digest": "🧠 <b>Resumen cripto, {time}</b>",
           "top": "🏆 <b>Top {n} monedas</b>", "gainers": "🚀 <b>Mayores subidas</b>",
           "losers": "🔻 <b>Mayores bajadas</b>", "ai": "🧠 <b>Análisis:</b>", "fact": "💡 <b>Dato curioso:</b>"},
    "de": {"hdr_market": "📊 <b>Marktübersicht, {time}</b>", "hdr_digest": "🧠 <b>Krypto-Digest, {time}</b>",
           "top": "🏆 <b>Top {n} Coins</b>", "gainers": "🚀 <b>Größte Gewinner</b>",
           "losers": "🔻 <b>Größte Verlierer</b>", "ai": "🧠 <b>Analyse:</b>", "fact": "💡 <b>Wussten Sie schon?</b>"},
}

EXTRA = {
    "en": {"custom": "⭐ <b>Your coins</b>", "alert_hdr": "🚨 <b>Whoa, big move!</b>", "alert_per": "1h",
           "fng": "Fear & Greed", "dom": "BTC dominance"},
    "ru": {"custom": "⭐ <b>Ваши монеты</b>", "alert_hdr": "🚨 <b>Ого, резкое движение!</b>", "alert_per": "за час",
           "fng": "Страх и жадность", "dom": "Доминирование BTC"},
    "fr": {"custom": "⭐ <b>Vos cryptos</b>", "alert_hdr": "🚨 <b>Wow, gros mouvement !</b>", "alert_per": "en 1 h",
           "fng": "Peur & Avidité", "dom": "Dominance BTC"},
    "es": {"custom": "⭐ <b>Tus monedas</b>", "alert_hdr": "🚨 <b>¡Uf, gran movimiento!</b>", "alert_per": "en 1 h",
           "fng": "Miedo y Codicia", "dom": "Dominancia BTC"},
    "de": {"custom": "⭐ <b>Ihre Coins</b>", "alert_hdr": "🚨 <b>Wow, starke Bewegung!</b>", "alert_per": "in 1 Std.",
           "fng": "Angst & Gier", "dom": "BTC-Dominanz"},
}
for _l in LABELS:
    LABELS[_l].update(EXTRA[_l])

# настроение рынка по среднему изменению топ-10 за 24ч: bull / up / calm / down / bear
MOOD = {
    "en": ["Green party on the market! 🟢🎉", "A pleasant green day 🌱", "Calm waters today 🌊",
           "A little red today 🍂", "Rough day out there — hold tight 🫡🔴"],
    "ru": ["На рынке зелёная вечеринка! 🟢🎉", "Приятный зелёный день 🌱", "Сегодня штиль 🌊",
           "Немного красного на рынке 🍂", "Тяжёлый день на рынке — держимся 🫡🔴"],
    "fr": ["Fête verte sur le marché ! 🟢🎉", "Une belle journée verte 🌱", "Mer calme aujourd’hui 🌊",
           "Un peu de rouge aujourd’hui 🍂", "Journée difficile — on tient bon 🫡🔴"],
    "es": ["¡Fiesta verde en el mercado! 🟢🎉", "Un agradable día en verde 🌱", "Aguas tranquilas hoy 🌊",
           "Un poco de rojo hoy 🍂", "Día duro — a aguantar 🫡🔴"],
    "de": ["Grüne Party am Markt! 🟢🎉", "Ein angenehmer grüner Tag 🌱", "Heute ruhige Gewässer 🌊",
           "Heute etwas Rot 🍂", "Harter Tag — durchhalten 🫡🔴"],
}

# классы индекса Fear & Greed (как их отдаёт alternative.me)
FNG_CLASS = {
    "ru": {"Extreme Fear": "Экстремальный страх", "Fear": "Страх", "Neutral": "Нейтрально",
           "Greed": "Жадность", "Extreme Greed": "Экстремальная жадность"},
    "fr": {"Extreme Fear": "Peur extrême", "Fear": "Peur", "Neutral": "Neutre",
           "Greed": "Avidité", "Extreme Greed": "Avidité extrême"},
    "es": {"Extreme Fear": "Miedo extremo", "Fear": "Miedo", "Neutral": "Neutral",
           "Greed": "Codicia", "Extreme Greed": "Codicia extrema"},
    "de": {"Extreme Fear": "Extreme Angst", "Fear": "Angst", "Neutral": "Neutral",
           "Greed": "Gier", "Extreme Greed": "Extreme Gier"},
    "en": {},
}

FALLBACK_MARKET = {
    "en": "The market (top 10) is {avg:+.2f}% on average over 24h.",
    "ru": "Рынок (топ-10) за сутки в среднем {avg:+.2f}%.",
    "fr": "Le marché (top 10) évolue de {avg:+.2f} % en moyenne sur 24 h.",
    "es": "El mercado (top 10) varía {avg:+.2f}% de media en 24 h.",
    "de": "Der Markt (Top 10) liegt im Schnitt bei {avg:+.2f}% in 24 Std.",
}

FALLBACK_FACTS = {
    "en": [
        "Bitcoin's genesis block (Jan 3, 2009) contains a headline from The Times about a second bank bailout.",
        "On May 22, 2010 a programmer paid 10,000 BTC for two pizzas — the first known purchase made with bitcoin.",
        "Bitcoin supply is capped at 21 million coins, and the miner reward halves every 210,000 blocks (roughly every four years).",
        "Ethereum launched on July 30, 2015, and in September 2022 it switched to Proof-of-Stake (The Merge), cutting its energy use by more than 99%.",
        "The Bitcoin whitepaper was published by Satoshi Nakamoto on October 31, 2008 and is only 9 pages long.",
        "The smallest unit of bitcoin is called a satoshi: 0.00000001 BTC.",
        "The Mt. Gox exchange went bankrupt in 2014 after losing about 850,000 BTC — one of the biggest events in market history.",
        "A smart contract is a program on a blockchain that runs automatically once preset conditions are met, with no intermediary.",
    ],
    "ru": [
        "Генезис-блок Bitcoin (3 января 2009) содержит заголовок газеты The Times о втором спасении банков.",
        "22 мая 2010 года программист заплатил 10 000 BTC за две пиццы — первая известная покупка за биткоин.",
        "Эмиссия биткоина ограничена 21 миллионом монет, а награда майнерам делится пополам каждые 210 000 блоков (примерно раз в четыре года).",
        "Ethereum запущен 30 июля 2015 года, а в сентябре 2022 перешёл на Proof-of-Stake (The Merge), сократив энергопотребление сети более чем на 99%.",
        "Белая книга Bitcoin опубликована Сатоши Накамото 31 октября 2008 года и занимает всего 9 страниц.",
        "Минимальная единица биткоина называется сатоши — это 0,00000001 BTC.",
        "Биржа Mt. Gox обанкротилась в 2014 году после потери около 850 000 BTC — одно из крупнейших событий в истории рынка.",
        "Смарт-контракт — это программа в блокчейне, которая исполняется автоматически при выполнении заданных условий, без посредника.",
    ],
    "fr": [
        "Le bloc de genèse de Bitcoin (3 janvier 2009) contient un titre du Times sur un second renflouement des banques.",
        "Le 22 mai 2010, un programmeur a payé 10 000 BTC pour deux pizzas : le premier achat connu en bitcoin.",
        "L’offre de bitcoins est plafonnée à 21 millions, et la récompense des mineurs est divisée par deux tous les 210 000 blocs (environ tous les quatre ans).",
        "Ethereum a été lancé le 30 juillet 2015 et est passé à la preuve d’enjeu (The Merge) en septembre 2022, réduisant sa consommation d’énergie de plus de 99 %.",
        "Le livre blanc de Bitcoin a été publié par Satoshi Nakamoto le 31 octobre 2008 et ne compte que 9 pages.",
        "La plus petite unité du bitcoin s’appelle le satoshi : 0,00000001 BTC.",
        "La plateforme Mt. Gox a fait faillite en 2014 après la perte d’environ 850 000 BTC, l’un des plus grands événements de l’histoire du marché.",
        "Un contrat intelligent est un programme sur une blockchain qui s’exécute automatiquement lorsque des conditions prédéfinies sont remplies, sans intermédiaire.",
    ],
    "es": [
        "El bloque génesis de Bitcoin (3 de enero de 2009) contiene un titular de The Times sobre un segundo rescate bancario.",
        "El 22 de mayo de 2010 un programador pagó 10 000 BTC por dos pizzas: la primera compra conocida con bitcoin.",
        "La oferta de bitcoin está limitada a 21 millones de monedas y la recompensa de los mineros se reduce a la mitad cada 210 000 bloques (aproximadamente cada cuatro años).",
        "Ethereum se lanzó el 30 de julio de 2015 y en septiembre de 2022 pasó a Proof-of-Stake (The Merge), reduciendo su consumo de energía en más de un 99 %.",
        "El libro blanco de Bitcoin lo publicó Satoshi Nakamoto el 31 de octubre de 2008 y tiene solo 9 páginas.",
        "La unidad más pequeña de bitcoin se llama satoshi: 0,00000001 BTC.",
        "El exchange Mt. Gox quebró en 2014 tras perder unos 850 000 BTC, uno de los mayores sucesos en la historia del mercado.",
        "Un contrato inteligente es un programa en una cadena de bloques que se ejecuta automáticamente al cumplirse unas condiciones, sin intermediarios.",
    ],
    "de": [
        "Der Genesis-Block von Bitcoin (3. Januar 2009) enthält eine Schlagzeile der Times über eine zweite Bankenrettung.",
        "Am 22. Mai 2010 bezahlte ein Programmierer 10.000 BTC für zwei Pizzen — der erste bekannte Kauf mit Bitcoin.",
        "Die Bitcoin-Menge ist auf 21 Millionen begrenzt, und die Miner-Belohnung halbiert sich alle 210.000 Blöcke (etwa alle vier Jahre).",
        "Ethereum startete am 30. Juli 2015 und wechselte im September 2022 zu Proof-of-Stake (The Merge), wodurch der Energieverbrauch um mehr als 99 % sank.",
        "Das Bitcoin-Whitepaper veröffentlichte Satoshi Nakamoto am 31. Oktober 2008; es umfasst nur 9 Seiten.",
        "Die kleinste Einheit von Bitcoin heißt Satoshi: 0,00000001 BTC.",
        "Die Börse Mt. Gox ging 2014 nach dem Verlust von rund 850.000 BTC pleite — eines der größten Ereignisse der Marktgeschichte.",
        "Ein Smart Contract ist ein Programm auf einer Blockchain, das automatisch ausgeführt wird, sobald festgelegte Bedingungen erfüllt sind — ohne Vermittler.",
    ],
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
    """Топ-100 по капитализации в нужной валюте. Кэш на CACHE_TTL сек: тысячи запросов
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
            f"?vs_currency={currency}&order=market_cap_desc&per_page=100&page=1"
            "&sparkline=false&price_change_percentage=1h,24h,7d"
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


def _pool(data: list, include_stables: bool = False) -> list:
    return [
        c for c in data
        if c["symbol"].upper() not in WRAPPED
        and (include_stables or c["symbol"].upper() not in STABLES)
    ]


def pick_coins(data: list, s: dict) -> list:
    n, mode = s["coins_count"], s["list_mode"]
    if mode == "custom":  # свои монеты (из топ-100) в порядке, выбранном пользователем
        by_id = {c["id"]: c for c in data}
        return [by_id[i] for i in s["custom_coins"] if i in by_id]
    pool = _pool(data, s["include_stables"])
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
    if s["show_change"] or s["list_mode"] in ("gainers", "losers"):
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
# Новости
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


# ------------------------------------------------------------------
# Gemini: ОДИН запрос = тексты сразу на всех языках (JSON); несколько ключей и моделей
# ------------------------------------------------------------------
_gemini_clients: dict = {}
_cooldown: dict = {}  # (индекс ключа, модель) -> время, до которого пропускаем (лимит 429)
_rr = {"i": 0}

JSON_TAIL = (
    "Return ONLY a valid JSON object with exactly these keys: en, ru, fr, es, de. Each value is "
    "the same text written naturally (not word-for-word) in that language: English, Russian, "
    "French, Spanish, German."
)
TONE = "Tone: friendly and light, a touch of humor, at most 1-2 fitting emojis."


def _client(idx: int):
    from google import genai
    from google.genai import types

    if idx not in _gemini_clients:
        _gemini_clients[idx] = genai.Client(
            api_key=config.GEMINI_KEYS[idx], http_options=types.HttpOptions(timeout=45000))
    return _gemini_clients[idx]


def _parse_multi(raw: str) -> dict:
    """JSON с текстами на всех языках -> {lang: text}. Бросает ValueError, если чего-то не хватает."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    data = json.loads(text)
    out = {l: data[l].strip() for l in LANG_NAMES
           if isinstance(data.get(l), str) and data[l].strip()}
    if len(out) != len(LANG_NAMES):
        raise ValueError("JSON has missing languages")
    return out


def _call_gemini(prompt: str):
    """Перебирает ключи и модели; ответ должен пройти разбор JSON, иначе пробуем дальше.
    Возвращает {lang: text} или None."""
    keys = config.GEMINI_KEYS
    if not keys:
        logger.warning("No Gemini API keys configured")
        return None
    from google.genai import types

    gen_config = types.GenerateContentConfig(temperature=0.8, response_mime_type="application/json")
    deadline = time.time() + 90
    start = _rr["i"] % len(keys)
    for idx in [(start + k) % len(keys) for k in range(len(keys))]:
        for model in config.GEMINI_MODELS:
            if time.time() > deadline:
                break
            if _cooldown.get((idx, model), 0) > time.time():
                continue
            for attempt in range(2):
                try:
                    resp = _client(idx).models.generate_content(
                        model=model, contents=prompt, config=gen_config)
                    result = _parse_multi(resp.text or "")
                    _rr["i"] = idx + 1  # следующий запрос начнём со следующего ключа
                    return result
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
    logger.warning("All Gemini keys/models failed")
    alerts.notify(
        "⚠️ Gemini недоступен (все ключи/модели). Пользователям отдаётся прошлый текст "
        "или запасной. Причины — в логах: journalctl -u cryptobot | grep Gemini",
        key="gemini_fail", cooldown=3600)
    return None


_recent_facts: collections.deque = collections.deque(maxlen=12)


def _gen_analysis():
    try:
        data = get_markets("usd")
    except Exception:
        data = []
    pool = _pool(data)
    ch = lambda c: c.get("price_change_percentage_24h_in_currency")
    top10 = [c for c in pool[:10] if ch(c) is not None]
    avg = sum(ch(c) for c in top10) / len(top10) if top10 else 0.0
    trend = "rising" if avg > 0.5 else "falling" if avg < -0.5 else "flat"
    top_line = ", ".join(f"{c['symbol'].upper()} {ch(c):+.1f}%" for c in top10) or "n/a"
    ranked = sorted((c for c in pool if ch(c) is not None), key=ch)
    movers = ", ".join(f"{c['symbol'].upper()} {ch(c):+.1f}%" for c in (ranked[-3:][::-1] + ranked[:3]))
    headlines = get_recent_headlines()
    news = ("Recent headlines:\n- " + "\n- ".join(headlines)
            if headlines else "There are no notable headlines in the last hours.")
    prompt = (
        "You are a friendly crypto analyst writing a short Telegram update.\n"
        f"Top coins, 24h change: {top_line}\n"
        f"Biggest 24h movers among the top 100: {movers or 'n/a'}\n"
        f"Overall the top-10 market is {trend}, {avg:+.2f}% on average over 24h.\n{news}\n\n"
        "TASK: write 2-3 sentences of market analysis. If the headlines contain IMPORTANT events "
        "(hacks, laws, court cases, ETFs, big moves), explain what happened and how it may affect "
        "the market; never invent anything that is not in the headlines or the data above. If there "
        "is no important news, say briefly that the news background is quiet and comment on the "
        f"market mood using the numbers above.\nNo greetings, no markdown, no buy/sell advice. {TONE}\n"
        + JSON_TAIL
    )
    texts = _call_gemini(prompt)
    if not texts:
        return None
    return {l: f"{LABELS[l]['ai']}\n{to_telegram_html(t)}" for l, t in texts.items()}


def _gen_fact():
    recent = " | ".join(_recent_facts) or "none"
    prompt = (
        f"Write ONE little-known, verifiable fact about \"{random.choice(FACT_TOPICS)}\" in the "
        "world of cryptocurrency: 2-3 sentences for a Telegram channel. Do not invent numbers, "
        "dates or names; if you are not sure about a detail, leave it out. No greetings, no "
        f"markdown. {TONE}\nDo not repeat or paraphrase these recent facts: {recent}\n" + JSON_TAIL
    )
    texts = _call_gemini(prompt)
    if not texts:
        return None
    _recent_facts.append(texts["en"][:90])
    return {l: f"{LABELS[l]['fact']}\n{to_telegram_html(t)}" for l, t in texts.items()}


def fallback_text(kind: str, lang: str):
    """Запасной текст без Gemini. analysis: реальное изменение рынка; fact: проверенный факт."""
    if kind == "fact":
        facts = FALLBACK_FACTS[lang]
        now = datetime.now(timezone.utc)
        fact = facts[(now.timetuple().tm_yday * 24 + now.hour) % len(facts)]
        return f"{LABELS[lang]['fact']}\n{html.escape(fact, quote=False)}"
    entry = _mcache.get("usd")
    if not entry:
        return None
    ch = [c.get("price_change_percentage_24h_in_currency") for c in _pool(entry["data"])[:10]]
    ch = [c for c in ch if c is not None]
    if not ch:
        return None
    return f"{LABELS[lang]['ai']}\n" + FALLBACK_MARKET[lang].format(avg=sum(ch) / len(ch))


_ai_cache: dict = {}  # kind -> (время, {язык: текст})
_ai_fail_until: dict = {}
_ai_warming: set = set()


def _warm_async(kind: str) -> None:
    if kind in _ai_warming:
        return
    _ai_warming.add(kind)

    def run():
        try:
            get_ai_text(kind, "en")
        finally:
            _ai_warming.discard(kind)

    threading.Thread(target=run, daemon=True, name=f"ai-warm-{kind}").start()


def get_ai_text(kind: str, lang: str, force: bool = False, cached_only: bool = False):
    """kind: 'analysis' | 'fact'. Один запрос к Gemini в час даёт тексты на всех языках, они
    кэшируются, а каждому пользователю отдаётся его язык.
    Цепочка: свежий кэш -> Gemini -> прошлый текст (до AI_STALE_HOURS ч) -> запасной текст.
    cached_only=True никогда не ждёт Gemini."""
    fresh_age = config.AI_CACHE_MIN * 60
    stale_age = config.AI_STALE_HOURS * 3600
    entry = _ai_cache.get(kind)

    if cached_only:
        if entry is None:
            _warm_async(kind)  # кэша ещё нет (свежий запуск): греем в фоне
        elif time.time() - entry[0] < stale_age and entry[1].get(lang):
            return entry[1][lang]
        return fallback_text(kind, lang)

    if entry and not force and time.time() - entry[0] < fresh_age and entry[1].get(lang):
        return entry[1][lang]
    with _lock_for("ai:" + kind):
        entry = _ai_cache.get(kind)
        if entry and not force and time.time() - entry[0] < fresh_age and entry[1].get(lang):
            return entry[1][lang]
        if force or time.time() >= _ai_fail_until.get(kind, 0):
            texts = _gen_fact() if kind == "fact" else _gen_analysis()
            if texts:
                _ai_cache[kind] = (time.time(), texts)
                return texts.get(lang) or fallback_text(kind, lang)
            _ai_fail_until[kind] = time.time() + 120  # не долбим Gemini при сбое
        if entry and time.time() - entry[0] < stale_age and entry[1].get(lang):
            return entry[1][lang]
        return fallback_text(kind, lang)


def cache_info() -> dict:
    now = time.time()
    return {
        "markets": {k: int(now - v["ts"]) for k, v in _mcache.items()},
        "ai": {k: int(now - v[0]) for k, v in _ai_cache.items()},
    }


# ------------------------------------------------------------------
# Fear & Greed, доминирование BTC, настроение рынка
# ------------------------------------------------------------------
_idx_cache: dict = {"ts": 0.0, "data": {}}


def get_indices(max_age: float = None) -> dict:
    """{'fng': (значение, класс) | None, 'dom': доля BTC в % | None}. Сбой одного источника
    не мешает отчёту: недостающая часть просто не показывается."""
    max_age = config.INDICES_TTL if max_age is None else max_age
    if _idx_cache["data"] and time.time() - _idx_cache["ts"] < max_age:
        return _idx_cache["data"]
    with _lock_for("idx"):
        if _idx_cache["data"] and time.time() - _idx_cache["ts"] < max_age:
            return _idx_cache["data"]
        fng = dom = None
        try:
            d = fetch_json("https://api.alternative.me/fng/?limit=1", retries=2)["data"][0]
            fng = (int(d["value"]), str(d["value_classification"]))
        except Exception as e:
            logger.warning("Fear & Greed unavailable: %s", e)
        try:
            dom = float(fetch_json("https://api.coingecko.com/api/v3/global",
                                   retries=2)["data"]["market_cap_percentage"]["btc"])
        except Exception as e:
            logger.warning("BTC dominance unavailable: %s", e)
        if fng or dom is not None:
            _idx_cache.update(ts=time.time(), data={"fng": fng, "dom": dom})
        return _idx_cache["data"]


def indices_line(lang: str) -> str:
    try:
        idx = get_indices()
    except Exception:
        return ""
    lab, parts = LABELS[lang], []
    if idx.get("fng"):
        value, cls = idx["fng"]
        parts.append(f"🌡 {lab['fng']}: <b>{value}</b> "
                     f"({html.escape(FNG_CLASS[lang].get(cls, cls), quote=False)})")
    if idx.get("dom") is not None:
        parts.append(f"₿ {lab['dom']}: <b>{idx['dom']:.1f}%</b>")
    return " · ".join(parts)


def mood_line(data: list, lang: str) -> str:
    ch = [c.get("price_change_percentage_24h_in_currency") for c in _pool(data)[:10]]
    ch = [c for c in ch if c is not None]
    if not ch:
        return ""
    avg = sum(ch) / len(ch)
    level = 0 if avg >= 3 else 1 if avg >= 1 else 2 if avg > -1 else 3 if avg > -3 else 4
    return MOOD[lang][level]


def top_coins_snapshot(data: list) -> list:
    """Список топ-100 для выбора «своих монет» в мини-приложении."""
    return [{"id": c["id"], "symbol": c["symbol"].upper(), "name": c.get("name", "")} for c in data]


# ------------------------------------------------------------------
# Алерты о резких движениях (изменение за 1 час)
# ------------------------------------------------------------------
def find_movers(data: list, min_pct: float) -> dict:
    """{coin_id: (символ, изменение за 1ч %)} для монет, изменившихся не меньше min_pct."""
    out = {}
    for c in data:
        ch = c.get("price_change_percentage_1h_in_currency")
        if ch is not None and abs(ch) >= min_pct:
            out[c["id"]] = (c["symbol"].upper(), ch)
    return out


def alert_scope(s: dict, data: list) -> list:
    """За какими монетами следим: свои (режим «Мои монеты») или топ-10 по капитализации."""
    if s["list_mode"] == "custom":
        return s["custom_coins"]
    return [c["id"] for c in _pool(data)[:10]]


def build_alert_text(s: dict, hits: list, price_data: list) -> str:
    """hits: [(coin_id, символ, изменение %)]."""
    lab = LABELS[s["lang"]]
    prices = {c["id"]: c.get("current_price") for c in price_data}
    lines = []
    for coin_id, sym, ch in hits:
        arrow = "📈" if ch > 0 else "📉"
        lines.append(f"{arrow} <b>{html.escape(sym)}</b> {ch:+.1f}% {lab['alert_per']} · "
                     f"{fmt_price(prices.get(coin_id), s['currency'])}")
    return lab["alert_hdr"] + "\n\n" + "\n".join(lines)


# ------------------------------------------------------------------
# Сборка сообщения по настройкам пользователя
# ------------------------------------------------------------------
def compose(s: dict, want_report: bool, want_analytics: bool, want_facts: bool = False,
            now: datetime = None, ai_cached_only: bool = False):
    """Текст сообщения или None. Аналитика и факт никогда не идут вместе:
    если пора аналитике, факт пропускается."""
    if want_analytics:
        want_facts = False
    now = now or datetime.now(timezone.utc)
    lang = s["lang"]
    lab = LABELS[lang]
    local = now.astimezone(ZoneInfo(s["tz"])).strftime("%d.%m.%Y %H:%M")
    parts, has_report = [], False
    if want_report:
        data = get_markets(s["currency"])
        block = build_coin_block(data, s)
        if block:
            mood = mood_line(data, lang)
            parts.append((f"<i>{mood}</i>\n\n" if mood else "") + block)
            has_report = True
            if s["show_indices"]:
                line = indices_line(lang)
                if line:
                    parts.append(line)
    if want_analytics:
        text = get_ai_text("analysis", lang, cached_only=ai_cached_only)
        if text:
            parts.append(text)
    if want_facts:
        text = get_ai_text("fact", lang, cached_only=ai_cached_only)
        if text:
            parts.append(text)
    if not parts:
        return None
    header = lab["hdr_market" if has_report else "hdr_digest"].format(time=local)
    return header + "\n\n" + "\n\n".join(parts)

