"""Каждая inline-кнопка, уходящая в Telegram, обязана иметь действие — иначе Telegram отклоняет
всё сообщение целиком («Text buttons are not allowed in the inline keyboard»)."""
import json

import pytest

ACTIONS = {"callback_data", "url", "switch_inline_query", "switch_inline_query_current_chat",
           "web_app", "login_url", "callback_game", "pay", "copy_text"}


def assert_valid(markup):
    data = json.loads(markup.to_json())
    for row in data["inline_keyboard"]:
        for btn in row:
            assert ACTIONS & set(btn), f"button without action: {btn}"
            if "callback_data" in btn:
                assert len(btn["callback_data"].encode()) <= 64, btn


@pytest.fixture
def inline_on(monkeypatch):
    import bot
    monkeypatch.setattr(bot, "INLINE_OK", True)
    monkeypatch.setattr(bot, "BOT_USERNAME", "TestBot")
    return bot


@pytest.mark.parametrize("lang", __import__("settings").LANGS)
def test_all_markups_serialize(inline_on, fake_market, lang, monkeypatch):
    import game
    import social
    import tools
    bot = inline_on
    assert_valid(bot.settings_markup(lang, share=True))
    assert_valid(bot.settings_markup(lang))
    assert_valid(bot.profile_markup(lang, lang_btn=True))
    assert_valid(bot.tz_markup(lang))
    assert_valid(bot.chart_markup(lang, fake_market[0], 7))
    assert_valid(social.invite_view(lang, 123, "TestBot", 0, True)[1])
    assert_valid(tools.card_markup(lang, fake_market[0], fav=False, share=True))
    s = __import__("settings").merged({"lang": lang})
    assert_valid(tools.alert_menu(s, "bitcoin")[1])
    assert_valid(game.new_card(lang)[1])
    assert_valid(game.after_markup(lang))


def test_share_button_keeps_empty_query():
    import social
    d = social.ShareButton("x").to_dict()
    assert d == {"text": "x", "switch_inline_query": ""}
