import time

import pytest

import chart
import market as M


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, str(data)

    def json(self):
        return self._data


def test_gemini_rest_parses_text_and_skips_thoughts(monkeypatch):
    data = {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True},
                                                  {"text": '{"en": "hi"}'}]}}]}
    monkeypatch.setattr(M._gemini_http, "post", lambda *a, **k: FakeResp(200, data))
    assert M._gemini_generate("k", "m", "p") == '{"en": "hi"}'


@pytest.mark.parametrize("status,err,marker", [(429, "RESOURCE_EXHAUSTED", "429"), (503, "UNAVAILABLE", "503"),
                                               (404, "NOT_FOUND", "NOT_FOUND")])
def test_gemini_rest_errors_keep_codes_for_retry_logic(monkeypatch, status, err, marker):
    monkeypatch.setattr(M._gemini_http, "post",
                        lambda *a, **k: FakeResp(status, {"error": {"status": err, "message": "x"}}))
    with pytest.raises(RuntimeError, match=marker):
        M._gemini_generate("k", "m", "p")


def test_gemini_key_sent_in_header_not_url(monkeypatch):
    seen = {}

    def post(url, headers=None, **k):
        seen["url"], seen["headers"] = url, headers
        return FakeResp(200, {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    monkeypatch.setattr(M._gemini_http, "post", post)
    M._gemini_generate("SECRET", "gemini-x", "p")
    assert "SECRET" not in seen["url"] and seen["headers"]["x-goog-api-key"] == "SECRET"


def test_currency_conversion_reuses_usd_without_api(monkeypatch):
    calls = []
    usd = [{"id": "bitcoin", "symbol": "btc", "current_price": 100.0, "market_cap": 1000.0,
            "price_change_percentage_24h_in_currency": 3.0}]
    monkeypatch.setitem(M._mcache, "usd", {"ts": time.time(), "data": usd, "src": "coingecko"})
    monkeypatch.setattr(M, "fx_rate", lambda cur: calls.append(cur) or 90.0)
    M._mcache.pop("rub", None)
    monkeypatch.setattr(M, "get_markets", lambda cur="usd", max_age=None: usd if cur == "usd" else M._converted(cur, 120))
    a = M.get_markets("rub")
    b = M.get_markets("rub")
    assert a[0]["current_price"] == pytest.approx(9000.0) and a[0]["price_change_percentage_24h_in_currency"] == 3.0
    assert a is b  # второй раз — из кэша, без пересчёта
    M._mcache.pop("rub", None)


def test_chart_history_cached_once_for_all_currencies(monkeypatch):
    fetches = []
    now = time.time()

    def cg(coin_id, days):
        fetches.append((coin_id, days))
        return [(now - 60, 100.0), (now, 110.0)]
    monkeypatch.setattr(chart, "_from_coingecko", cg)
    monkeypatch.setattr(chart, "_cg_budget_ok", lambda: True)
    monkeypatch.setattr(M, "fx_rate", lambda cur: {"usd": 1.0, "eur": 0.9, "rub": 90.0}[cur])
    chart._hist.clear()
    usd, _ = chart.history("bitcoin", "btc", "usd", 1)
    rub, _ = chart.history("bitcoin", "btc", "rub", 1)
    eur, _ = chart.history("bitcoin", "btc", "eur", 1)
    assert fetches == [("bitcoin", 1)]  # один запрос к API на три валюты
    assert rub[-1][1] == pytest.approx(9900.0) and eur[-1][1] == pytest.approx(99.0) and usd[-1][1] == 110.0


def test_chart_file_id_reused(monkeypatch, fake_market):
    now = time.time()
    monkeypatch.setattr(chart, "history", lambda *a: ([(now - 60, 100.0), (now, 110.0)], "x"))
    chart._png_cache.clear()
    png, _ = chart.build(fake_market[0], "usd", 1, "UTC", "en", "@b")
    assert isinstance(png, bytes)
    chart.remember_file_id(fake_market[0], "usd", 1, "UTC", "@b", "FILE123")
    again, _ = chart.build(fake_market[0], "usd", 1, "UTC", "en", "@b")
    assert again == "FILE123"
