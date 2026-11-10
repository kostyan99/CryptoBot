"""Данные рынка (CoinGecko, кэш), новости, Gemini (аналитика и факты), сборка сообщения."""
import calendar
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

LANG_NAMES = {"ru": "Russian", "en": "English", "fr": "French", "es": "Spanish", "de": "German", "uk": "Ukrainian"}

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
    "uk": {"hdr_market": "📊 <b>Огляд ринку на {time}</b>", "hdr_digest": "🧠 <b>Крипто-дайджест на {time}</b>",
           "top": "🏆 <b>Топ-{n} монет</b>", "gainers": "🚀 <b>Лідери зростання</b>",
           "losers": "🔻 <b>Лідери падіння</b>", "ai": "🧠 <b>Аналітика:</b>", "fact": "💡 <b>Цікавий факт:</b>"},
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
    "uk": {"custom": "⭐ <b>Ваші монети</b>", "alert_hdr": "🚨 <b>Ого, різкий рух!</b>", "alert_per": "за годину",
           "fng": "Страх і жадібність", "dom": "Домінування BTC"},
}
WEEKLY_LABELS = {
    "en": {"weekly_title": "🗓 <b>Your week in crypto</b>", "weekly_best": "🏅 Best of the week: <b>{sym}</b> {chg}",
           "weekly_worst": "🥶 Toughest week: <b>{sym}</b> {chg}"},
    "ru": {"weekly_title": "🗓 <b>Ваша неделя в крипте</b>", "weekly_best": "🏅 Лучшая за неделю: <b>{sym}</b> {chg}",
           "weekly_worst": "🥶 Самая тяжёлая: <b>{sym}</b> {chg}"},
    "fr": {"weekly_title": "🗓 <b>Votre semaine en crypto</b>", "weekly_best": "🏅 Meilleure de la semaine : <b>{sym}</b> {chg}",
           "weekly_worst": "🥶 Semaine la plus dure : <b>{sym}</b> {chg}"},
    "es": {"weekly_title": "🗓 <b>Tu semana en cripto</b>", "weekly_best": "🏅 Mejor de la semana: <b>{sym}</b> {chg}",
           "weekly_worst": "🥶 La más floja: <b>{sym}</b> {chg}"},
    "de": {"weekly_title": "🗓 <b>Ihre Krypto-Woche</b>", "weekly_best": "🏅 Beste der Woche: <b>{sym}</b> {chg}",
           "weekly_worst": "🥶 Schwächste Woche: <b>{sym}</b> {chg}"},
    "uk": {"weekly_title": "🗓 <b>Ваш тиждень у крипті</b>", "weekly_best": "🏅 Найкраща за тиждень: <b>{sym}</b> {chg}",
           "weekly_worst": "🥶 Найважча: <b>{sym}</b> {chg}"},
}
for _l in LABELS:
    LABELS[_l].update(EXTRA[_l])
    LABELS[_l].update(WEEKLY_LABELS[_l])

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
    "uk": ["На ринку зелена вечірка! 🟢🎉", "Приємний зелений день 🌱", "Сьогодні штиль 🌊",
           "Трохи червоного на ринку 🍂", "Важкий день на ринку — тримаємося 🫡🔴"],
}

# настроение недели (по среднему 7-дневному изменению монет пользователя)
WEEK_MOOD = {
    "en": ["What a week — green all over! 🟢🎉", "A solid green week 🌱", "A quiet, steady week 🌊",
           "A bit of a rough week 🍂", "A tough week — you made it through 🫡"],
    "ru": ["Какая неделя — всё в зелёном! 🟢🎉", "Хорошая зелёная неделя 🌱", "Спокойная ровная неделя 🌊",
           "Немного хмурая неделя 🍂", "Тяжёлая неделя — но мы выстояли 🫡"],
    "fr": ["Quelle semaine — tout en vert ! 🟢🎉", "Une belle semaine verte 🌱", "Une semaine calme et stable 🌊",
           "Une semaine un peu difficile 🍂", "Semaine dure — on a tenu bon 🫡"],
    "es": ["¡Qué semana — todo en verde! 🟢🎉", "Una buena semana en verde 🌱", "Una semana tranquila y estable 🌊",
           "Una semana algo complicada 🍂", "Semana dura — la superamos 🫡"],
    "de": ["Was für eine Woche — alles im grünen Bereich! 🟢🎉", "Eine solide grüne Woche 🌱",
           "Eine ruhige, stabile Woche 🌊", "Eine etwas holprige Woche 🍂", "Harte Woche — aber geschafft 🫡"],
    "uk": ["Оце тиждень — усе в зеленому! 🟢🎉", "Гарний зелений тиждень 🌱", "Спокійний рівний тиждень 🌊",
           "Трохи похмурий тиждень 🍂", "Важкий тиждень — але ми вистояли 🫡"],
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
    "uk": {"Extreme Fear": "Екстремальний страх", "Fear": "Страх", "Neutral": "Нейтрально",
           "Greed": "Жадібність", "Extreme Greed": "Екстремальна жадібність"},
}

# Расчётная аналитика без Gemini: средний рост топ-10, лидеры, индекс страха и жадности, доминирование BTC
FALLBACK_AI = {
    "en": {"up": "The top 10 is up {avg} on average over 24h.", "down": "The top 10 is down {avg} on average over 24h.",
           "flat": "The top 10 is roughly flat over 24h ({avg}).", "leaders": "Leaders: {items}.",
           "drop": "Biggest drop: {items}.", "and": " and ",
           "fng": "The Fear & Greed index is at {v} — {mood}.", "dom": "BTC dominance: {v}.",
           "moods": {"Extreme Fear": "extreme fear dominates", "Fear": "fear prevails",
                     "Neutral": "the mood is neutral", "Greed": "optimism prevails",
                     "Extreme Greed": "euphoria, stay careful"}},
    "ru": {"up": "Топ-10 криптовалют показывает средний рост {avg} за сутки.",
           "down": "Топ-10 криптовалют показывает среднее падение {avg} за сутки.",
           "flat": "Топ-10 криптовалют почти без изменений за сутки ({avg}).",
           "leaders": "Лидерами являются {items}.", "drop": "Сильнее всех снизилась: {items}.", "and": " и ",
           "fng": "Индекс страха и жадности находится на уровне {v}, {mood}.", "dom": "Доминирование BTC: {v}.",
           "moods": {"Extreme Fear": "что говорит о сильном страхе", "Fear": "что говорит о преобладании страха",
                     "Neutral": "что говорит о нейтральных настроениях",
                     "Greed": "что говорит о преобладании оптимизма",
                     "Extreme Greed": "что говорит об эйфории, будьте осторожны"}},
    "fr": {"up": "Le top 10 progresse de {avg} en moyenne sur 24 h.", "down": "Le top 10 recule de {avg} en moyenne sur 24 h.",
           "flat": "Le top 10 est quasi stable sur 24 h ({avg}).", "leaders": "En tête : {items}.",
           "drop": "Plus forte baisse : {items}.", "and": " et ",
           "fng": "L’indice Peur & Avidité est à {v} — {mood}.", "dom": "Dominance BTC : {v}.",
           "moods": {"Extreme Fear": "la peur extrême domine", "Fear": "la peur domine",
                     "Neutral": "le sentiment est neutre", "Greed": "l’optimisme domine",
                     "Extreme Greed": "euphorie, restez prudent"}},
    "es": {"up": "El top 10 sube de media {avg} en 24 h.", "down": "El top 10 baja de media {avg} en 24 h.",
           "flat": "El top 10 está casi sin cambios en 24 h ({avg}).", "leaders": "Lideran: {items}.",
           "drop": "Mayor caída: {items}.", "and": " y ",
           "fng": "El índice de Miedo y Codicia está en {v} — {mood}.", "dom": "Dominancia de BTC: {v}.",
           "moods": {"Extreme Fear": "domina el miedo extremo", "Fear": "predomina el miedo",
                     "Neutral": "el ánimo es neutral", "Greed": "predomina el optimismo",
                     "Extreme Greed": "euforia, ojo con el exceso"}},
    "de": {"up": "Die Top 10 liegen im Schnitt {avg} im Plus (24 Std.).", "down": "Die Top 10 liegen im Schnitt {avg} im Minus (24 Std.).",
           "flat": "Die Top 10 sind in 24 Std. nahezu unverändert ({avg}).", "leaders": "Spitzenreiter: {items}.",
           "drop": "Größter Verlust: {items}.", "and": " und ",
           "fng": "Der Angst-&-Gier-Index steht bei {v} — {mood}.", "dom": "BTC-Dominanz: {v}.",
           "moods": {"Extreme Fear": "extreme Angst dominiert", "Fear": "Angst überwiegt",
                     "Neutral": "die Stimmung ist neutral", "Greed": "Optimismus überwiegt",
                     "Extreme Greed": "Euphorie, Vorsicht geboten"}},
    "uk": {"up": "Топ-10 криптовалют показує середнє зростання {avg} за добу.",
           "down": "Топ-10 криптовалют показує середнє падіння {avg} за добу.",
           "flat": "Топ-10 криптовалют майже без змін за добу ({avg}).",
           "leaders": "Лідери: {items}.", "drop": "Найсильніше знизилася: {items}.", "and": " і ",
           "fng": "Індекс страху та жадібності на рівні {v}, {mood}.", "dom": "Домінування BTC: {v}.",
           "moods": {"Extreme Fear": "що свідчить про сильний страх", "Fear": "що свідчить про переважання страху",
                     "Neutral": "що свідчить про нейтральні настрої",
                     "Greed": "що свідчить про переважання оптимізму",
                     "Extreme Greed": "що свідчить про ейфорію, будьте обережні"}},
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
    "uk": [
        "Генезис-блок Bitcoin (3 січня 2009) містить заголовок газети The Times про друге рятування банків.",
        "22 травня 2010 року програміст заплатив 10 000 BTC за дві піци — перша відома покупка за біткоїн.",
        "Емісія біткоїна обмежена 21 мільйоном монет, а винагорода майнерам зменшується вдвічі кожні 210 000 блоків (приблизно раз на чотири роки).",
        "Ethereum запущено 30 липня 2015 року, а у вересні 2022 він перейшов на Proof-of-Stake (The Merge), скоротивши енергоспоживання мережі більш ніж на 99%.",
        "Білу книгу Bitcoin Сатоші Накамото опублікував 31 жовтня 2008 року, і вона займає лише 9 сторінок.",
        "Найменша одиниця біткоїна називається сатоші — це 0,00000001 BTC.",
        "Біржа Mt. Gox збанкрутувала у 2014 році після втрати близько 850 000 BTC — одна з найбільших подій в історії ринку.",
        "Смарт-контракт — це програма в блокчейні, яка виконується автоматично, щойно виконано задані умови, без посередника.",
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
                if attempt == retries - 1:
                    break  # последняя попытка: не ждём впустую
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


# ------------------------------------------------------------------
# Резервный источник курсов: CoinPaprika (+ курсы валют), если CoinGecko недоступен
# ------------------------------------------------------------------
STALE_PREFER_SEC = 600  # до 10 минут лучше отдать прошлые данные CoinGecko, дальше — резерв
FALLBACK_TTL = 60  # резервные данные живут минуту: потом снова пробуем CoinGecko
_pp_cache: dict = {"ts": 0.0, "data": None}
_fx_cache: dict = {"ts": 0.0, "rates": {}}


_cg_rates: dict = {"ts": 0.0, "rates": {}}
CG_RATES_TTL = 600


def fx_rate(currency: str) -> float:
    """Сколько единиц валюты за 1 USD. Сначала курсы самого CoinGecko (/exchange_rates, один запрос
    на все валюты раз в 10 минут — цены совпадают с сайтом CoinGecko), затем open.er-api.com (кэш 6 ч),
    затем соотношение цен BTC в кэше."""
    if currency == "usd":
        return 1.0
    if time.time() - _cg_rates["ts"] > CG_RATES_TTL:
        with _lock_for("cg_rates"):
            if time.time() - _cg_rates["ts"] > CG_RATES_TTL:
                try:
                    raw = fetch_json("https://api.coingecko.com/api/v3/exchange_rates", retries=1)["rates"]
                    usd = float(raw["usd"]["value"])
                    _cg_rates.update(ts=time.time(), rates={k: float(v["value"]) / usd for k, v in raw.items()})
                except Exception as e:
                    # не долбим API при сбое: следующая попытка через минуту
                    _cg_rates["ts"] = time.time() - CG_RATES_TTL + 60
                    logger.warning("CoinGecko exchange rates unavailable: %s", e)
    if _cg_rates["rates"].get(currency):
        return _cg_rates["rates"][currency]
    if time.time() - _fx_cache["ts"] > 6 * 3600 or currency.upper() not in _fx_cache["rates"]:
        try:
            rates = fetch_json("https://open.er-api.com/v6/latest/USD", retries=2)["rates"]
            _fx_cache.update(ts=time.time(), rates=rates)
        except Exception as e:
            logger.warning("FX rates unavailable: %s", e)
    rate = _fx_cache["rates"].get(currency.upper())
    if rate:
        return float(rate)
    usd, cur = _mcache.get("usd"), _mcache.get(currency)
    if usd and cur:  # из последних данных CoinGecko: цена BTC в валюте / цена BTC в USD
        b_usd = next((c["current_price"] for c in usd["data"] if c["id"] == "bitcoin"), None)
        b_cur = next((c["current_price"] for c in cur["data"] if c["id"] == "bitcoin"), None)
        if b_usd and b_cur:
            return b_cur / b_usd
    raise RuntimeError(f"no FX rate for {currency}")


def _known_ids() -> dict:
    """{(SYMBOL, name.lower()): coingecko_id, SYMBOL: id} — чтобы id монет у резерва совпадали
    с CoinGecko (на них завязаны алерты, портфель, «мои монеты» и игра)."""
    src = (_mcache.get("usd") or {}).get("data")
    if not src:
        try:
            import db  # локально: market не зависит от БД, кроме этого запасного пути
            src = json.loads(db.get_meta("top_coins") or "[]")
        except Exception:
            src = []
    out = {}
    for c in src:
        sym = c["symbol"].upper()
        out.setdefault((sym, (c.get("name") or "").lower()), c["id"])
        out.setdefault(sym, c["id"])
    return out


def _paprika_usd() -> list:
    if _pp_cache["data"] and time.time() - _pp_cache["ts"] < FALLBACK_TTL:
        return _pp_cache["data"]
    raw = fetch_json("https://api.coinpaprika.com/v1/tickers?quotes=USD", retries=2, timeout=25)
    if not isinstance(raw, list) or not raw:
        raise ValueError("unexpected CoinPaprika response")
    raw = sorted((t for t in raw if t.get("rank")), key=lambda t: t["rank"])[:250]
    _pp_cache.update(ts=time.time(), data=raw)
    return raw


def fallback_markets(currency: str) -> list:
    """Топ-200 из CoinPaprika в формате CoinGecko (id сопоставлены с CoinGecko)."""
    raw, rate, known = _paprika_usd(), fx_rate(currency), _known_ids()
    out, seen = [], set()
    for t in raw:
        q = t["quotes"]["USD"]
        sym = t["symbol"].upper()
        cid = known.get((sym, t["name"].lower())) or known.get(sym) or t["id"].split("-", 1)[-1]
        if cid in seen or not q.get("price"):
            continue
        seen.add(cid)
        conv = lambda v: v * rate if v is not None else None  # noqa: E731
        out.append({
            "id": cid, "symbol": t["symbol"].lower(), "name": t["name"], "image": None,
            "current_price": conv(q.get("price")), "market_cap": conv(q.get("market_cap")),
            "market_cap_rank": t["rank"], "total_volume": conv(q.get("volume_24h")),
            "high_24h": None, "low_24h": None, "ath": conv(q.get("ath_price")),
            "ath_change_percentage": q.get("percent_from_price_ath"),
            "price_change_percentage_1h_in_currency": q.get("percent_change_1h"),
            "price_change_percentage_24h_in_currency": q.get("percent_change_24h"),
            "price_change_percentage_7d_in_currency": q.get("percent_change_7d"),
        })
        if len(out) >= 200:
            break
    if not out:
        raise ValueError("empty fallback data")
    return out


_MONEY_FIELDS = ("current_price", "market_cap", "total_volume", "high_24h", "low_24h", "ath")


def _converted(currency: str, max_age: float) -> list:
    """Курсы в валюте = курсы в USD × курс валюты. Так к CoinGecko идёт ОДИН запрос на обновление,
    а не по запросу на каждую валюту пользователей (меньше лимитов 429). Пересчёт кэшируется,
    пока не обновились данные в USD. Проценты изменений — как в USD."""
    usd = get_markets("usd", max_age)
    base = _mcache.get("usd") or {}
    entry = _mcache.get(currency)
    rate = fx_rate(currency)
    if entry and entry.get("base_ts") == base.get("ts") and entry.get("rate") == rate:
        return entry["data"]
    data = [{**c, **{f: c[f] * rate for f in _MONEY_FIELDS if c.get(f) is not None}} for c in usd]
    _mcache[currency] = {"ts": base.get("ts", time.time()), "data": data, "src": base.get("src", "?") + "+fx",
                         "base_ts": base.get("ts"), "rate": rate}
    return data


def source(currency: str = "usd") -> str:
    return (_mcache.get(currency) or {}).get("src", "")


def get_markets(currency: str = "usd", max_age: float = None) -> list:
    """Топ-200 по капитализации в нужной валюте. Кэш на CACHE_TTL сек: тысячи запросов
    пользователей = один запрос к CoinGecko. Пока кто-то обновляет кэш, остальные
    получают предыдущие данные. При сбое CoinGecko: кэш до 10 минут, затем резервный
    источник (CoinPaprika), и в крайнем случае кэш не старше STALE_MAX_SEC."""
    max_age = config.CACHE_TTL if max_age is None else max_age
    if currency != "usd":
        return _converted(currency, max_age)
    entry = _mcache.get(currency)
    if entry and time.time() - entry["ts"] < min(max_age, entry.get("ttl", max_age)):
        return entry["data"]

    lock = _lock_for("m:" + currency)
    if not lock.acquire(blocking=(entry is None or max_age == 0)):
        return entry["data"]
    try:
        entry = _mcache.get(currency)
        if max_age > 0 and entry and time.time() - entry["ts"] < min(max_age, entry.get("ttl", max_age)):
            return entry["data"]
        url = (
            "https://api.coingecko.com/api/v3/coins/markets"
            f"?vs_currency={currency}&order=market_cap_desc&per_page=200&page=1"
            "&sparkline=false&price_change_percentage=1h,24h,7d"
        )
        try:
            data = fetch_json(url, retries=2)
            if not isinstance(data, list) or not data:
                raise ValueError("unexpected CoinGecko response")
        except Exception as e:
            # свежие данные CoinGecko (пусть и чуть устаревшие) точнее резерва
            if entry and entry.get("src") != "coinpaprika" and time.time() - entry["ts"] < STALE_PREFER_SEC:
                logger.warning("CoinGecko failed, serving recent cache (%s)", currency)
                return entry["data"]
            try:
                data = fallback_markets(currency)
                _mcache[currency] = {"ts": time.time(), "data": data, "src": "coinpaprika", "ttl": FALLBACK_TTL}
                logger.warning("CoinGecko failed (%s), using CoinPaprika for %s", e, currency)
                alerts.notify("⚠️ CoinGecko недоступен — курсы идут из резервного источника (CoinPaprika).",
                              key="cg_fallback", cooldown=3600)
                return data
            except Exception as fe:
                logger.warning("Fallback source failed too: %s", fe)
            if entry and time.time() - entry["ts"] < config.STALE_MAX_SEC:
                logger.warning("CoinGecko failed, serving stale cache (%s)", currency)
                return entry["data"]
            raise
        _mcache[currency] = {"ts": time.time(), "data": data, "src": "coingecko"}
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


def fmt_big(value, currency: str) -> str:
    """1 920 000 000 000 -> $1.92T (капитализация, объёмы, стоимость портфеля)."""
    if value is None:
        return "—"
    sym, prefix = CURRENCY_FMT.get(currency, ("$", True))
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= div:
            num = f"{value / div:.2f}{suf}"
            break
    else:
        num = f"{value:.2f}"
    return f"{sym}{num}" if prefix else f"{num}{sym}"


def fmt_money(value, currency: str) -> str:
    """Сумма с разделителями: $12 345.67 (для портфеля)."""
    if value is None:
        return "—"
    if abs(value) < 1:
        return fmt_price(value, currency) if value >= 0 else "-" + fmt_price(-value, currency)
    sym, prefix = CURRENCY_FMT.get(currency, ("$", True))
    sign = "-" if value < 0 else ""
    num = f"{abs(value):,.2f}".replace(",", " ")
    return f"{sign}{sym}{num}" if prefix else f"{sign}{num}{sym}"


def fmt_pct(change) -> str:
    """Короткое изменение с цветной точкой: 🟢 +1.23% / 🔴 -0.50%."""
    if change is None:
        return "⚪ —"
    return f"{'🟢' if change >= 0 else '🔴'} {change:+.2f}%"


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
_gemini_http = requests.Session()  # keep-alive: повторные запросы без нового TLS-рукопожатия
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_cooldown: dict = {}  # (индекс ключа, модель) -> время, до которого пропускаем (лимит 429)
_rr = {"i": 0}

JSON_TAIL = (
    "Return ONLY a valid JSON object with exactly these keys: en, ru, fr, es, de, uk. Each value is "
    "the same text written naturally (not word-for-word) in that language: English, Russian, "
    "French, Spanish, German, Ukrainian."
)
TONE = "Tone: friendly and light, a touch of humor, at most 1-2 fitting emojis."


def _gemini_generate(key: str, model: str, prompt: str) -> str:
    """Один запрос к Gemini через REST API. Раньше использовалась библиотека google-genai:
    ради одного HTTP-запроса она добавляла ~40 МБ памяти и ~1 с к запуску.
    Текст ошибки содержит HTTP-код и статус (429/RESOURCE_EXHAUSTED, 503/UNAVAILABLE…) —
    по нему _call_gemini решает, что делать дальше."""
    r = _gemini_http.post(
        GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},  # ключ не в URL и не в логах
        json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"}},
        timeout=(10, 90),
    )
    if r.status_code != 200:
        try:
            err = r.json().get("error", {})
            detail = f"{err.get('status', '')} {err.get('message', '')}"
        except ValueError:
            detail = r.text[:200]
        raise RuntimeError(f"{r.status_code} {detail}")
    data = r.json()
    cands = data.get("candidates") or []
    parts = (cands[0].get("content") or {}).get("parts") or [] if cands else []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text:
        reason = cands[0].get("finishReason") if cands else (data.get("promptFeedback") or {}).get("blockReason")
        raise ValueError(f"empty Gemini response ({reason})")
    return text


def _json_text(raw: str):
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    return json.loads(text)


def _parse_multi(raw: str) -> dict:
    """JSON с текстами на всех языках -> {lang: text}. Бросает ValueError, если чего-то не хватает."""
    data = _json_text(raw)
    out = {l: data[l].strip() for l in LANG_NAMES
           if isinstance(data.get(l), str) and data[l].strip()}
    if len(out) != len(LANG_NAMES):
        raise ValueError("JSON has missing languages")
    return out


def _call_gemini(prompt: str, parse):
    """Перебирает ключи и модели; ответ должен пройти разбор `parse`, иначе пробуем следующий
    вариант. Медленная модель (504/таймаут) не блокирует остальные: сразу идём дальше, а её
    пропускаем на 15 минут. Возвращает результат разбора или None."""

    keys = config.GEMINI_KEYS
    if not keys:
        logger.warning("No Gemini API keys configured")
        return None

    deadline = time.time() + 240
    start = _rr["i"] % len(keys)

    for idx in [(start + k) % len(keys) for k in range(len(keys))]:
        for model in config.GEMINI_MODELS:
            if time.time() > deadline:
                break

            if _cooldown.get((idx, model), 0) > time.time():
                continue

            try:
                result = parse(_gemini_generate(keys[idx], model, prompt))
                _rr["i"] = idx + 1  # следующий запрос начнём со следующего ключа
                return result

            except Exception as e:
                msg = str(e).replace(keys[idx], "***")

                logger.warning(
                    "Gemini key#%d %s failed: %s",
                    idx + 1,
                    model,
                    msg[:200],
                )

                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    _cooldown[(idx, model)] = time.time() + 600  # лимит: пропускаем 10 минут

                elif "404" in msg or "NOT_FOUND" in msg:
                    for k in range(len(keys)):  # модель снята или недоступна: сутки не трогаем
                        _cooldown[(k, model)] = time.time() + 86400

                elif any(x in msg for x in (
                    "504",
                    "DEADLINE_EXCEEDED",
                    "timed out",
                    "Timeout",
                )):
                    for k in range(len(keys)):  # медленная модель медленна для любого ключа: 15 минут
                        _cooldown[(k, model)] = time.time() + 900

                elif any(x in msg for x in (
                    "500",
                    "503",
                    "UNAVAILABLE",
                    "overloaded",
                )):
                    time.sleep(2)  # перегрузка: короткая пауза и следующий вариант

    logger.warning("All Gemini keys/models failed")

    alerts.notify(
        "⚠️ Gemini недоступен (все ключи/модели). Пользователям отдаётся прошлый текст "
        "или запасной. Причины — в логах: journalctl -u cryptobot | grep Gemini",
        key="gemini_fail",
        cooldown=3600,
    )

    return None
   

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
    texts = _call_gemini(prompt, _parse_multi)
    if not texts:
        return None
    return {l: f"{LABELS[l]['ai']}\n{to_telegram_html(t)}" for l, t in texts.items()}


def _parse_facts_batch(raw: str) -> list:
    data = _json_text(raw)
    items = data.get("facts") if isinstance(data, dict) else data
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        texts = {l: it[l].strip() for l in LANG_NAMES if isinstance(it.get(l), str) and it[l].strip()}
        topic = str(it.get("topic", "")).strip()[:80]
        if topic and len(texts) == len(LANG_NAMES):
            out.append((topic, texts))
    if not out:
        raise ValueError("no valid facts in batch")
    return out


def _parse_keep(raw: str) -> list:
    data = _json_text(raw)
    keep = data.get("keep") if isinstance(data, dict) else None
    if not isinstance(keep, list) or any(isinstance(x, bool) or not isinstance(x, int) for x in keep):
        raise ValueError("bad verification response")
    return keep


def generate_fact_batch(n: int = 10, recent_topics=()) -> list:
    """Один запрос генерирует n фактов сразу на 5 языках, второй запрос — строгая проверка
    (оставляем только факты, в которых модель уверена). Непроверенное не сохраняется.
    Возвращает [(topic, {lang: text})]."""
    ideas = ", ".join(random.sample(FACT_TOPICS, min(8, len(FACT_TOPICS))))
    prompt = (
        f"Write {n} DIFFERENT little-known but well-documented facts about cryptocurrency, "
        "blockchain and their history, 2-3 sentences each, for a Telegram channel. "
        f"Spread them across topics such as: {ideas}. "
        f"Do NOT cover these recent topics: {', '.join(recent_topics) or 'none'}. "
        "Include only facts you are highly confident are accurate and widely verifiable; never "
        "invent numbers, dates, names or quotes; if unsure, skip the fact. No greetings, no "
        f"markdown. {TONE}\n"
        'Return ONLY valid JSON: {"facts": [{"topic": "<2-4 word English label>", "en": "...", '
        '"ru": "...", "fr": "...", "es": "...", "de": "...", "uk": "..."}]} where every language value is the '
        "same fact written naturally in that language."
    )
    batch = _call_gemini(prompt, _parse_facts_batch)
    if not batch:
        return []
    listing = "\n".join(f"{i}. {texts['en']}" for i, (_, texts) in enumerate(batch))
    check = (
        "You are a strict fact-checker. Below are numbered crypto facts. Return ONLY JSON like "
        '{"keep": [0, 2]} listing the numbers of facts that are CERTAINLY accurate and verifiable; '
        "exclude any fact with doubtful numbers, dates, names or wording.\n" + listing
    )
    keep = _call_gemini(check, _parse_keep)
    if keep is None:
        return []  # не удалось проверить — не сохраняем
    return [batch[i] for i in keep if 0 <= i < len(batch)]


def _parse_translations(raw: str) -> dict:
    data = _json_text(raw)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("bad translation response")
    out = {}
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("id"), int) and isinstance(it.get("text"), str) and it["text"].strip():
            out[it["id"]] = it["text"].strip()
    if not out:
        raise ValueError("no translations")
    return out


def translate_facts(items: list, lang: str) -> dict:
    """Переводит факты пула на новый язык одним запросом к Gemini. items: [(id, english)].
    Возвращает {id: перевод} (только для известных id)."""
    if not items:
        return {}
    listing = "\n".join(json.dumps({"id": fid, "text": text}, ensure_ascii=False) for fid, text in items)
    prompt = (
        f"Translate each crypto fact below from English into {LANG_NAMES[lang]}. Write naturally, as a native "
        "speaker would for a Telegram channel, keep the meaning, numbers, names and dates exactly, keep emojis. "
        'Return ONLY valid JSON: {"items": [{"id": <same id>, "text": "<translation>"}]}.\n' + listing
    )
    result = _call_gemini(prompt, _parse_translations) or {}
    known = {fid for fid, _ in items}
    return {fid: text for fid, text in result.items() if fid in known}


def format_fact(texts: dict, lang: str) -> str:
    return f"{LABELS[lang]['fact']}\n{to_telegram_html(texts.get(lang) or texts['en'])}"


def fallback_text(kind: str, lang: str):
    """Запасной текст без Gemini. analysis: реальное изменение рынка; fact: проверенный факт."""
    if kind == "fact":
        facts = FALLBACK_FACTS[lang]
        now = datetime.now(timezone.utc)
        fact = facts[(now.timetuple().tm_yday * 24 + now.hour) % len(facts)]
        return f"{LABELS[lang]['fact']}\n{html.escape(fact, quote=False)}"
    return _computed_analysis(lang)


def _computed_analysis(lang: str):
    """Аналитика из уже посчитанных данных (без Gemini): среднее топ-10, лидеры/падение,
    Fear & Greed, доминирование BTC. None, если курсов в кэше ещё нет."""
    entry = _mcache.get("usd")
    if not entry:
        return None
    t = FALLBACK_AI[lang]
    ch = lambda c: c.get("price_change_percentage_24h_in_currency")
    pool = _pool(entry["data"])
    top10 = [ch(c) for c in pool[:10] if ch(c) is not None]
    if not top10:
        return None
    avg = sum(top10) / len(top10)
    lines = [t["up" if avg > 0.5 else "down" if avg < -0.5 else "flat"].format(avg=f"{avg:+.1f}%")]

    def items(coins):
        return t["and"].join(f"{html.escape(c['symbol'].upper())} ({ch(c):+.1f}%)" for c in coins)

    ranked = sorted((c for c in pool if ch(c) is not None), key=ch)
    leaders = [c for c in ranked[::-1][:2] if ch(c) > 0]
    if leaders:
        lines.append(t["leaders"].format(items=items(leaders)))
    if ranked and ch(ranked[0]) < 0:
        lines.append(t["drop"].format(items=items(ranked[:1])))
    idx = _idx_cache["data"] or {}
    if idx.get("fng"):
        value, cls = idx["fng"]
        lines.append(t["fng"].format(v=value, mood=t["moods"].get(cls, cls)))
    if idx.get("dom") is not None:
        lines.append(t["dom"].format(v=f"{idx['dom']:.1f}%"))
    return f"{LABELS[lang]['ai']}\n" + "\n".join(lines)


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
    """kind: 'analysis' (факты теперь берутся из пула в БД). Один запрос к Gemini в час даёт тексты на всех языках, они
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
            texts = _gen_analysis()
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
        "markets": {k: f"{int(now - v['ts'])} ({v.get('src', '?')})" for k, v in _mcache.items()},
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
            try:  # резерв: CoinPaprika
                dom = float(fetch_json("https://api.coinpaprika.com/v1/global",
                                       retries=1)["bitcoin_dominance_percentage"])
            except Exception:
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
            now: datetime = None, ai_cached_only: bool = False, fact_text: str = None,
            portfolio_text: str = None):
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
            if portfolio_text:
                parts.append(portfolio_text)
            if s["show_indices"]:
                line = indices_line(lang)
                if line:
                    parts.append(line)
    if want_analytics:
        text = get_ai_text("analysis", lang, cached_only=ai_cached_only)
        if text:
            parts.append(text)
    if want_facts:  # факт из пула в БД; если пул пуст — проверенный запасной факт
        parts.append(fact_text or fallback_text("fact", lang))
    if not parts:
        return None
    header = lab["hdr_market" if has_report else "hdr_digest"].format(time=local)
    return header + "\n\n" + "\n\n".join(parts)


def compose_weekly(s: dict, game_line: str = None, now: datetime = None, portfolio_text: str = None):
    """Итоги недели по монетам пользователя (7-дневное изменение). None, если данных нет."""
    now = now or datetime.now(timezone.utc)
    lang, lab = s["lang"], LABELS[s["lang"]]
    data = get_markets(s["currency"])
    if s["list_mode"] == "custom":
        coins = pick_coins(data, s)
    else:
        coins = _pool(data, s["include_stables"])[:5]
    key = "price_change_percentage_7d_in_currency"
    rows = [c for c in coins if c.get(key) is not None]
    if not rows:
        return None
    best, worst = max(rows, key=lambda c: c[key]), min(rows, key=lambda c: c[key])
    avg = sum(c[key] for c in rows) / len(rows)
    level = 0 if avg >= 8 else 1 if avg >= 2 else 2 if avg > -2 else 3 if avg > -8 else 4
    local = now.astimezone(ZoneInfo(s["tz"])).strftime("%d.%m.%Y")
    parts = [f"{lab['weekly_title']} · {local}\n<i>{WEEK_MOOD[lang][level]}</i>"]
    summary = [lab["weekly_best"].format(sym=html.escape(best["symbol"].upper()), chg=fmt_change(best[key]))]
    if worst["id"] != best["id"]:
        summary.append(lab["weekly_worst"].format(sym=html.escape(worst["symbol"].upper()),
                                                   chg=fmt_change(worst[key])))
    parts.append("\n".join(summary))
    lines = []
    for i, c in enumerate(rows, start=1):
        sym = c["symbol"].upper()
        emoji = (COIN_EMOJIS.get(sym, "⚡️") + " ") if s["show_emoji"] else ""
        lines.append(f"{keycap(i)} {emoji}<b>{html.escape(sym)}</b>: "
                     f"{fmt_price(c.get('current_price'), s['currency'])} ({fmt_change(c[key])} · 7d)")
    parts.append("\n".join(lines))
    if portfolio_text:
        parts.append(portfolio_text)
    if s["show_indices"]:
        idx = indices_line(lang)
        if idx:
            parts.append(idx)
    if game_line:
        parts.append(game_line)
    return "\n\n".join(parts)
