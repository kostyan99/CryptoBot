"""График цены монеты (PNG): история из CoinGecko, при сбое или лимите — из Binance.
Рисуем через Pillow с двойным разрешением и сглаживанием — быстро даже на Orange Pi."""
import io
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from PIL import Image, ImageChops, ImageDraw, ImageFont

import market as M

logger = logging.getLogger("chart")

PERIODS = (1, 7, 30)  # дней
HISTORY_TTL = {1: 300, 7: 900, 30: 1800}  # кэш истории, секунд
CG_CHART_PER_MIN = 6  # бережём лимит CoinGecko для основных курсов: остальное — через Binance
BINANCE = {1: ("15m", 96), 7: ("1h", 168), 30: ("4h", 180)}

CT = {
    "en": {"btn": "📈 Chart", "card": "📊 Card", "p": {1: "24h", 7: "7d", 30: "30d"}, "lo": "Low", "hi": "High",
           "fail": "😕 Couldn't build the chart right now — please try again in a minute.",
           "usage": "Send a ticker, e.g. <code>/chart BTC</code> or <code>/chart ETH 30d</code>"},
    "ru": {"btn": "📈 График", "card": "📊 Карточка", "p": {1: "24ч", 7: "7д", 30: "30д"}, "lo": "Мин", "hi": "Макс",
           "fail": "😕 Не получилось построить график — попробуйте через минуту.",
           "usage": "Отправьте тикер, например <code>/chart BTC</code> или <code>/chart ETH 30d</code>"},
    "fr": {"btn": "📈 Graphique", "card": "📊 Fiche", "p": {1: "24 h", 7: "7 j", 30: "30 j"}, "lo": "Bas", "hi": "Haut",
           "fail": "😕 Impossible de créer le graphique pour l’instant — réessayez dans une minute.",
           "usage": "Envoyez un ticker, par ex. <code>/chart BTC</code> ou <code>/chart ETH 30d</code>"},
    "es": {"btn": "📈 Gráfico", "card": "📊 Ficha", "p": {1: "24 h", 7: "7 d", 30: "30 d"}, "lo": "Mín", "hi": "Máx",
           "fail": "😕 No se pudo crear el gráfico ahora — inténtalo en un minuto.",
           "usage": "Envía un ticker, p. ej. <code>/chart BTC</code> o <code>/chart ETH 30d</code>"},
    "de": {"btn": "📈 Chart", "card": "📊 Karte", "p": {1: "24 Std.", 7: "7 T.", 30: "30 T."}, "lo": "Tief", "hi": "Hoch",
           "fail": "😕 Der Chart konnte gerade nicht erstellt werden — bitte in einer Minute erneut versuchen.",
           "usage": "Senden Sie einen Ticker, z. B. <code>/chart BTC</code> oder <code>/chart ETH 30d</code>"},
}


PERIOD_WORDS = {
    1: {"1", "24", "1d", "24h", "24ч", "d", "day", "день", "сутки"},
    7: {"7", "7d", "7д", "w", "1w", "week", "неделя", "нед"},
    30: {"30", "30d", "30д", "m", "1m", "month", "месяц", "мес"},
}


def parse_period(arg: str):
    """'7d' -> 7, '30д' -> 30, '24h' -> 1; не период -> None."""
    a = (arg or "").strip().lower()
    return next((d for d, words in PERIOD_WORDS.items() if a in words), None)


# ------------------------------------------------------------------
# История цены
# ------------------------------------------------------------------
_hist: dict = {}
_hist_lock = threading.Lock()
_cg_calls: deque = deque()


def _cg_budget_ok() -> bool:
    now = time.time()
    with _hist_lock:
        while _cg_calls and now - _cg_calls[0] > 60:
            _cg_calls.popleft()
        if len(_cg_calls) >= CG_CHART_PER_MIN:
            return False
        _cg_calls.append(now)
        return True


def _from_coingecko(coin_id: str, days: int) -> list:
    data = M.fetch_json(f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
                        f"?vs_currency=usd&days={days}", retries=1, timeout=15)
    return [(ts / 1000, p) for ts, p in data["prices"] if p is not None]


def _from_binance(symbol: str, days: int) -> list:
    interval, limit = BINANCE[days]
    rows = M.fetch_json(f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}USDT"
                        f"&interval={interval}&limit={limit}", retries=1, timeout=15)
    return [(r[6] / 1000, float(r[4])) for r in rows]  # время закрытия, цена закрытия


def history(coin_id: str, symbol: str, currency: str, days: int) -> tuple:
    """([(unix_ts, цена в валюте)], источник). История хранится в USD — один кэш и один запрос
    к API на монету для всех валют; в валюту пересчитываем на лету."""
    points, src = _history_usd(coin_id, symbol, days)
    rate = M.fx_rate(currency)
    return ([(t, p * rate) for t, p in points] if rate != 1.0 else points), src


def _history_usd(coin_id: str, symbol: str, days: int) -> tuple:
    """([(unix_ts, цена в USD)], источник). Бросает исключение, если оба источника недоступны."""
    key = (coin_id, days)
    hit = _hist.get(key)
    if hit and time.time() - hit[0] < HISTORY_TTL[days]:
        return hit[1], hit[2]
    points, src, err = None, None, None
    if _cg_budget_ok():
        try:
            points, src = _from_coingecko(coin_id, days), "CoinGecko"
        except Exception as e:
            err = e
    if not points and symbol.upper() not in M.STABLES:
        try:
            points, src = _from_binance(symbol, days), "Binance"
        except Exception as e:
            err = e
    if not points or len(points) < 2:
        if hit:  # лучше вчерашний график, чем никакого
            return hit[1], hit[2]
        raise RuntimeError(f"no history for {coin_id}: {err}")
    if len(points) > 400:  # прореживаем: на картинке всё равно ~1000 пикселей
        step = len(points) / 400
        points = [points[int(i * step)] for i in range(400)] + [points[-1]]
    _hist[key] = (time.time(), points, src)
    if len(_hist) > 2000:
        for k in sorted(_hist, key=lambda k: _hist[k][0])[:500]:
            _hist.pop(k, None)
    return points, src


# ------------------------------------------------------------------
# Рисование
# ------------------------------------------------------------------
SCALE = 2
W, H = 1280, 720
BG, GRID, TEXT, SUB = (14, 17, 23), (33, 40, 50), (230, 237, 243), (139, 148, 158)
GREEN, RED = (46, 189, 133), (246, 70, 93)
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
_fonts: dict = {}


def _font(size: int, bold: bool = False):
    key = (size, bold)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(FONT_DIR + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
                                             size * SCALE)
        except OSError:
            _fonts[key] = ImageFont.load_default(size * SCALE)
    return _fonts[key]


def render(points: list, symbol: str, name: str, currency: str, days: int, tz: str,
           source: str = "", watermark: str = "") -> bytes:
    """PNG 1280×720: линия цены с градиентной заливкой, сетка, мин/макс, текущая цена."""
    s = SCALE
    img = Image.new("RGBA", (W * s, H * s), BG + (255,))
    d = ImageDraw.Draw(img, "RGBA")
    prices = [p for _, p in points]
    first, last = prices[0], prices[-1]
    change = (last - first) / first * 100 if first else 0.0
    color = GREEN if change >= 0 else RED

    # шапка: тикер и название слева, цена и изменение справа
    d.text((48 * s, 34 * s), symbol.upper(), font=_font(46, True), fill=TEXT)
    sym_w = d.textlength(symbol.upper(), font=_font(46, True))
    d.text((48 * s + sym_w + 16 * s, 52 * s), name[:28], font=_font(26), fill=SUB)
    price_txt = M.fmt_price(last, currency)
    d.text(((W - 48) * s, 34 * s), price_txt, font=_font(46, True), fill=TEXT, anchor="ra")
    chg_txt = f"{change:+.2f}%  ·  {CT['en']['p'][days]}"
    d.text(((W - 48) * s, 96 * s), chg_txt, font=_font(26, True), fill=color, anchor="ra")

    # область графика
    left, right, top, bottom = 48 * s, (W - 150) * s, 150 * s, (H - 80) * s
    lo, hi = min(prices), max(prices)
    pad = (hi - lo) * 0.08 or (hi * 0.01 or 1)
    ymin, ymax = lo - pad, hi + pad
    t0, t1 = points[0][0], points[-1][0]
    span = (t1 - t0) or 1

    def xy(t, p):
        return (left + (t - t0) / span * (right - left), bottom - (p - ymin) / (ymax - ymin) * (bottom - top))

    for i in range(5):  # горизонтальная сетка и цены справа
        y = top + (bottom - top) * i / 4
        d.line([(left, y), (right, y)], fill=GRID, width=s)
        value = ymax - (ymax - ymin) * i / 4
        d.text((right + 16 * s, y), M.fmt_price(value, currency), font=_font(20), fill=SUB, anchor="lm")
    zone = ZoneInfo(tz)
    for i in range(5):  # подписи времени снизу
        t = t0 + span * i / 4
        x = left + (right - left) * i / 4
        label = datetime.fromtimestamp(t, timezone.utc).astimezone(zone).strftime("%H:%M" if days == 1 else "%d.%m")
        anchor = "la" if i == 0 else "ra" if i == 4 else "ma"
        d.text((x, bottom + 16 * s), label, font=_font(20), fill=SUB, anchor=anchor)

    line = [xy(t, p) for t, p in points]
    # градиентная заливка под линией: слои только размером с область графика, а не всей картинки
    # (в 2,5 раза меньше временной памяти на каждую отрисовку)
    box = (int(left), int(top), int(right) + 1, int(bottom) + 1)
    bw, bh = box[2] - box[0], box[3] - box[1]
    shifted = [(x - box[0], y - box[1]) for x, y in line]
    poly_mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(poly_mask).polygon(shifted + [(shifted[-1][0], bh), (shifted[0][0], bh)], fill=255)
    grad = Image.linear_gradient("L").rotate(180).resize((1, bh)).resize((bw, bh))
    grad = grad.point(lambda v: int(v * 0.38))
    fill = Image.new("RGBA", (bw, bh), color + (0,))
    fill.putalpha(ImageChops.multiply(grad, poly_mask))
    img.alpha_composite(fill, dest=box[:2])
    d = ImageDraw.Draw(img, "RGBA")
    d.line(line, fill=color, width=4 * s, joint="curve")

    # минимум и максимум
    i_hi, i_lo = prices.index(hi), prices.index(lo)
    for idx, above in ((i_hi, True), (i_lo, False)):
        x, y = line[idx]
        d.ellipse([x - 6 * s, y - 6 * s, x + 6 * s, y + 6 * s], fill=TEXT)
        anchor = ("l" if x < (left + right) / 2 else "r") + ("d" if above else "a")
        dx = 12 * s if anchor[0] == "l" else -12 * s
        d.text((x + dx, y + (-10 * s if above else 10 * s)), M.fmt_price(prices[idx], currency),
               font=_font(20, True), fill=TEXT, anchor=anchor)
    # текущая точка с «ореолом»
    x, y = line[-1]
    halo = tuple(int(c * 0.35 + b * 0.65) for c, b in zip(color, BG))  # полупрозрачный ореол
    d.ellipse([x - 14 * s, y - 14 * s, x + 14 * s, y + 14 * s], fill=halo)
    d.ellipse([x - 8 * s, y - 8 * s, x + 8 * s, y + 8 * s], fill=color)

    # подвал: источник и подпись бота
    if source:
        d.text((48 * s, (H - 22) * s), f"data: {source}", font=_font(18), fill=SUB, anchor="ls")
    if watermark:
        d.text(((W - 48) * s, (H - 22) * s), watermark, font=_font(22, True), fill=SUB, anchor="rs")

    out = io.BytesIO()
    img.convert("RGB").resize((W, H), Image.LANCZOS).save(out, "PNG", optimize=True)
    return out.getvalue()


# ------------------------------------------------------------------
# Готовый график для пользователя
# ------------------------------------------------------------------
_png_cache: dict = {}  # (coin, currency, days, tz) -> (время, png, подпись-данные)


def _key(coin: dict, currency: str, days: int, tz: str, watermark: str) -> tuple:
    return coin["id"], currency, days, tz, watermark


def build(coin: dict, currency: str, days: int, tz: str, lang: str, watermark: str = "") -> tuple:
    """(фото, подпись HTML). Картинка кэшируется на минуту: популярные монеты не рисуем заново.
    Если эту картинку уже отправляли, фото — это file_id Telegram (повторная отправка без загрузки)."""
    key = _key(coin, currency, days, tz, watermark)
    hit = _png_cache.get(key)
    if hit and time.time() - hit[0] < 60:
        png, stats = hit[3] or hit[1], hit[2]
    else:
        points, src = history(coin["id"], coin["symbol"], currency, days)
        png = render(points, coin["symbol"], coin.get("name") or "", currency, days, tz, src, watermark)
        prices = [p for _, p in points]
        stats = (prices[0], prices[-1], min(prices), max(prices))
        _png_cache[key] = (time.time(), png, stats, None)
        if len(_png_cache) > 300:
            for k in sorted(_png_cache, key=lambda k: _png_cache[k][0])[:100]:
                _png_cache.pop(k, None)
    first, last, lo, hi = stats
    ct = CT[lang]
    change = (last - first) / first * 100 if first else 0.0
    caption = (f"📈 <b>{coin['symbol'].upper()}</b> · {ct['p'][days]}: {M.fmt_pct(change)}\n"
               f"{ct['lo']} {M.fmt_price(lo, currency)} · {ct['hi']} {M.fmt_price(hi, currency)}")
    return png, caption


def remember_file_id(coin: dict, currency: str, days: int, tz: str, watermark: str, file_id: str) -> None:
    """Запоминаем file_id отправленной картинки: следующие пользователи получат её мгновенно."""
    key = _key(coin, currency, days, tz, watermark)
    hit = _png_cache.get(key)
    if hit and file_id:
        _png_cache[key] = (hit[0], hit[1], hit[2], file_id)
