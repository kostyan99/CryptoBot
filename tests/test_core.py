from datetime import date, datetime, timezone

import pytest

import db
import game
import market as M
import settings as S
import social


def test_fmt_big_and_money():
    assert M.fmt_big(1.92e12, "usd") == "$1.92T"
    assert M.fmt_big(5.5e6, "rub") == "5.50M ₽"
    assert M.fmt_money(12345.678, "usd") == "$12 345.68"
    assert M.fmt_money(-50, "eur") == "-€50.00"
    assert M.fmt_pct(None) == "⚪ —" and M.fmt_pct(-1).startswith("🔴")


def test_next_slot_aligned_to_local_hour():
    after = datetime(2026, 11, 10, 10, 30, tzinfo=timezone.utc)
    nxt = S.next_slot(after, "Europe/Kyiv", 4, 0)  # Kyiv = UTC+2 -> 12:30 local, next 16:00 local
    assert nxt == datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)


def test_quiet_hours_over_midnight():
    s = S.merged({"quiet_enabled": True, "quiet_start": 23, "quiet_end": 7, "tz": "UTC"})
    assert not S.is_allowed_now(s, datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc))
    assert S.is_allowed_now(s, datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc))


def test_validation():
    with pytest.raises(ValueError):
        S.validate_partial({"report_interval": 5})
    with pytest.raises(ValueError):
        S.validate_partial({"custom_coins": ["BAD ID"]})
    assert S.validate_partial({"show_portfolio": False}) == {"show_portfolio": False}
    assert S.merged({"lang": "xx"})["lang"] == "en"  # мусор в БД игнорируется


def test_profiles_are_valid():
    for name, prof in S.PROFILES.items():
        s = S.merged({})
        s.update(S.validate_partial(prof))
        S.validate_consistency(s)


def test_weekly_retry_stays_same_day():
    s = S.merged({"days": [0, 1, 2, 3, 4], "tz": "UTC"})
    now = datetime(2026, 11, 15, 19, 5, tzinfo=timezone.utc)  # воскресенье
    assert db._next_allowed(s, now, datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc)) is None


def test_game_scoring_and_daily_bonus():
    assert game.score(0, 1) == 10 and game.score(0, 24) == 25 and game.score(9, 4) == 25
    assert db.daily_bonus(1) == 5 and db.daily_bonus(2) == 7 and db.daily_bonus(100) == db.DAILY_BONUS_MAX


def test_game_card_callback_data_fits_telegram_limit():
    for _ in range(20):
        _, kb = game.new_card("ru")
        for row in kb.keyboard:
            for b in row:
                assert len((b.callback_data or "").encode()) <= 64


def test_game_card_specific_coin_and_horizon():
    text, kb = game.new_card("en", coin_id="ethereum", horizon=24)
    assert "ETH" in text and "24 h" in text
    assert kb.keyboard[0][0].callback_data == "g:p:ethereum:u:24"


def test_referral_payload():
    assert social.parse_payload("r123__bitcoin") == (123, "bitcoin")
    assert social.parse_payload("r42") == (42, None)
    assert social.parse_payload("c__the-open-network") == (None, "the-open-network")
    assert social.parse_payload("junk!!") == (None, None)
    link = social.ref_link("MyBot", 123456789, "bitcoin")
    assert link.endswith("?start=r123456789__bitcoin") and len(link.split("=")[1]) <= 64


def test_detect_lang():
    assert social.detect_lang("ru") == "ru" and social.detect_lang("de-AT") == "de"
    assert social.detect_lang("be") == "ru" and social.detect_lang("pt") is None and social.detect_lang(None) is None


def test_inline_results_build(fake_market):
    res = social.inline_results("", "en", "usd", "MyBot", 1)
    assert res[0].id == "overview" and len(res) >= 2
    res = social.inline_results("eth", "ru", "usd", "MyBot", 1)
    assert res[0].id == "c:ethereum"


def test_translations_complete():
    keys = set(game.GT["en"])
    for lang in game.GT:
        assert set(game.GT[lang]) == keys, lang
    for lang in social.ST:
        assert set(social.ST[lang]) == set(social.ST["en"]), lang
    assert date  # noqa


def test_bot_texts_and_commands_complete():
    import bot
    keys = set(bot.T["en"])
    for lang in bot.T:
        assert set(bot.T[lang]) == keys, lang
        assert len(bot.CMD_DESC[lang]) == len(bot.CMD_ORDER), lang
        bot.main_keyboard(lang)
        bot.profile_markup(lang, lang_btn=True)
    assert bot.utc_offset("America/St_Johns") in ("-3:30", "-2:30")
    assert bot.utc_offset("Asia/Kolkata") == "+5:30"
