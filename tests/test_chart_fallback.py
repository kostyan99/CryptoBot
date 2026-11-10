import time

import pytest

import chart
import market as M

PAPRIKA = [
    {"id": "btc-bitcoin", "name": "Bitcoin", "symbol": "BTC", "rank": 1,
     "quotes": {"USD": {"price": 100.0, "market_cap": 1000.0, "volume_24h": 50.0, "percent_change_1h": 0.1,
                        "percent_change_24h": 1.0, "percent_change_7d": 2.0, "ath_price": 200.0,
                        "percent_from_price_ath": -50.0}}},
    {"id": "ton-toncoin", "name": "Toncoin", "symbol": "TON", "rank": 2,
     "quotes": {"USD": {"price": 5.0}}},
    {"id": "newc-newcoin", "name": "Newcoin", "symbol": "NEWC", "rank": 3,
     "quotes": {"USD": {"price": 1.0}}},
    {"id": "btc-fakebtc", "name": "Fake BTC", "symbol": "BTC", "rank": 4,
     "quotes": {"USD": {"price": 1.0}}},
]


@pytest.fixture
def paprika(monkeypatch):
    monkeypatch.setattr(M, "_paprika_usd", lambda: PAPRIKA)
    monkeypatch.setattr(M, "fx_rate", lambda cur: {"usd": 1.0, "rub": 90.0}[cur])
    monkeypatch.setitem(M._mcache, "usd", {"ts": time.time(), "data": [
        {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"},
        {"id": "the-open-network", "symbol": "ton", "name": "Toncoin"}], "src": "coingecko"})


def test_fallback_maps_ids_to_coingecko(paprika):
    data = M.fallback_markets("usd")
    ids = [c["id"] for c in data]
    assert ids[:3] == ["bitcoin", "the-open-network", "newcoin"]  # по кэшу CoinGecko, иначе из id CoinPaprika
    assert ids.count("bitcoin") == 1  # дубликат тикера не затирает настоящую монету
    btc = data[0]
    assert btc["market_cap_rank"] == 1 and btc["price_change_percentage_7d_in_currency"] == 2.0


def test_fallback_converts_currency(paprika):
    btc = M.fallback_markets("rub")[0]
    assert btc["current_price"] == pytest.approx(9000.0) and btc["ath"] == pytest.approx(18000.0)
    assert btc["price_change_percentage_24h_in_currency"] == 1.0


def test_kzt_is_converted_from_usd(monkeypatch, fake_market):
    monkeypatch.setattr(M, "fx_rate", lambda cur: 500.0)
    M._mcache.pop("kzt", None)
    data = M._converted("kzt", 120)
    assert data[0]["current_price"] == pytest.approx(97000 * 500)
    assert data[0]["price_change_percentage_24h_in_currency"] == 2.0
    M._mcache.pop("kzt", None)


@pytest.mark.parametrize("arg,days", [("7d", 7), ("30д", 30), ("24h", 1), ("week", 7), ("btc", None), ("", None)])
def test_parse_period(arg, days):
    assert chart.parse_period(arg) == days


def test_render_png():
    now = time.time()
    points = [(now - 3600 * (48 - i), 100 + (i % 7) * 3 - i * 0.5) for i in range(48)]
    png = chart.render(points, "btc", "Bitcoin", "rub", 7, "Europe/Kyiv", "Binance", "@Bot")
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 10000


def test_build_uses_history_and_caption(monkeypatch, fake_market):
    now = time.time()
    monkeypatch.setattr(chart, "history", lambda *a: ([(now - 60, 100.0), (now, 110.0)], "Binance"))
    chart._png_cache.clear()
    png, caption = chart.build(fake_market[0], "usd", 1, "UTC", "ru")
    assert "BTC" in caption and "+10.00%" in caption and "Макс $110.00" in caption


def test_chart_texts_complete():
    for lang in chart.CT:
        assert set(chart.CT[lang]) == set(chart.CT["en"]) and set(chart.CT[lang]["p"]) == set(chart.PERIODS)
