"""Тесты не ходят в сеть и в БД: подставляем фиктивное окружение и данные рынка."""
import os
import sys

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("DATABASE_URL", "postgresql://test@localhost/test")
os.environ.pop("ADMIN_CHAT_ID", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

FAKE = [
    {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "current_price": 97000.0, "market_cap": 1.92e12,
     "market_cap_rank": 1, "total_volume": 4.1e10, "high_24h": 98000.0, "low_24h": 95000.0, "ath": 108000.0,
     "ath_change_percentage": -10.2, "price_change_percentage_1h_in_currency": 0.3,
     "price_change_percentage_24h_in_currency": 2.0, "price_change_percentage_7d_in_currency": 5.0},
    {"id": "ethereum", "symbol": "eth", "name": "Ethereum", "current_price": 3500.0, "market_cap": 4.2e11,
     "market_cap_rank": 2, "price_change_percentage_24h_in_currency": -1.0,
     "price_change_percentage_7d_in_currency": -3.0},
    {"id": "tether", "symbol": "usdt", "name": "Tether", "current_price": 1.0, "market_cap_rank": 3,
     "price_change_percentage_24h_in_currency": 0.0},
    {"id": "solana", "symbol": "sol", "name": "Solana", "current_price": 180.0, "market_cap_rank": 5,
     "price_change_percentage_24h_in_currency": 4.0},
    {"id": "fake-btc", "symbol": "btc", "name": "Fake BTC", "current_price": 1.0, "market_cap_rank": 150},
]


@pytest.fixture(autouse=True)
def fake_market(monkeypatch):
    import market
    monkeypatch.setattr(market, "get_markets", lambda currency="usd", max_age=None: FAKE)
    return FAKE
