import pytest

import tools


@pytest.mark.parametrize("raw,expected", [
    ("100000", 100000), ("100 000", 100000), ("1,5", 1.5), ("1,000,000", 1e6), ("1,234.5", 1234.5),
    ("$97.5k", 97500), ("2м", 2e6), ("0.00001234", 0.00001234), (".5", 0.5), ("97 500 ₽", 97500),
])
def test_parse_number_ok(raw, expected):
    assert tools.parse_number(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["", "abc", "-5", "0", "1.2.3", "1e5", "10%"])
def test_parse_number_rejects(raw):
    assert tools.parse_number(raw) is None


def test_resolve_prefers_biggest_coin_for_ticker(fake_market):
    assert tools.resolve("BTC", fake_market)["id"] == "bitcoin"
    assert tools.resolve("$btc", fake_market)["id"] == "bitcoin"


@pytest.mark.parametrize("q,coin", [("биткоин", "bitcoin"), ("эфир", "ethereum"), ("Solana", "solana"),
                                    ("ethereum", "ethereum")])
def test_resolve_names_and_aliases(fake_market, q, coin):
    assert tools.resolve(q, fake_market)["id"] == coin


def test_resolve_unknown(fake_market):
    assert tools.resolve("nosuchcoin", fake_market) is None
    assert tools.resolve("x" * 50, fake_market) is None


def test_search_prefix(fake_market):
    ids = [c["id"] for c in tools.search("so", fake_market)]
    assert ids == ["solana"]


def test_fmt_amount():
    assert tools.fmt_amount(0.5) == "0.5"
    assert tools.fmt_amount(2.0) == "2"
    assert tools.fmt_amount(12345.5) == "12 345.5"


def test_card_text_contains_key_facts(fake_market):
    text = tools.card_text(fake_market[0], "en", "usd", holding=0.5, alerts_n=2)
    assert "Bitcoin" in text and "$97 000.00" in text and "$1.92T" in text
    assert "0.5 BTC" in text and "Active alerts: 2" in text


def test_portfolio_valuation(fake_market):
    rows, total, d24, d7 = tools._valuate([("bitcoin", "BTC", 1.0), ("missing", "X", 5)], fake_market)
    assert total == pytest.approx(97000)
    assert d24 == pytest.approx(97000 - 97000 / 1.02)
    assert len(rows) == 1


def test_portfolio_line_respects_setting():
    import settings as S
    s = S.merged({})
    assert "Portfolio" in tools.portfolio_line(s, [("bitcoin", "BTC", 1.0)])
    s["show_portfolio"] = False
    assert tools.portfolio_line(s, [("bitcoin", "BTC", 1.0)]) is None
    assert tools.portfolio_line(S.merged({}), []) is None


def test_pending_roundtrip():
    tools.set_pending(1, "alert", "bitcoin")
    assert tools.pop_pending(1) == ("alert", "bitcoin")
    assert tools.pop_pending(1) is None


def test_all_languages_have_same_keys():
    keys = set(tools.TT["en"])
    for lang, texts in tools.TT.items():
        assert set(texts) == keys, lang
