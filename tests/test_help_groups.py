import json
import re

import pytest

import help_texts

LANGS = ["en", "ru", "fr", "es", "de"]


@pytest.mark.parametrize("lang", LANGS)
def test_help_complete_and_fits_telegram(lang):
    import bot
    text = bot.T[lang]["help"].format(bot="CryptoHelperBot")
    assert len(text) < 4096
    for cmd in ("/top", "/price", "/chart", "/alert", "/alerts", "/add", "/portfolio", "/game", "/leaderboard",
                "/invite", "/settings", "/profile", "/stop", "/start", "/cancel", "/delete", "@CryptoHelperBot"):
        assert cmd in text, (lang, cmd)
    # каждая команда из меню Telegram упомянута в справке
    for cmd in bot.CMD_ORDER:
        assert re.search(rf"/{cmd}\b", text), (lang, cmd)
    # HTML-разметка сбалансирована (иначе Telegram не примет сообщение)
    for tag in ("b", "code"):
        assert text.count(f"<{tag}>") == text.count(f"</{tag}>"), (lang, tag)


@pytest.mark.parametrize("lang", LANGS)
def test_descriptions_within_limits(lang):
    assert len(help_texts.DESCRIPTION[lang]) <= 512
    assert len(help_texts.SHORT_DESCRIPTION[lang]) <= 120


def test_group_markup_strips_webapp_and_reply_keyboard(monkeypatch):
    import bot
    import config
    monkeypatch.setattr(config, "WEBAPP_URL", "https://example.com")
    kb = bot.settings_markup("ru", share=False)
    assert any(b.web_app for row in kb.keyboard for b in row)
    group_kb = bot.for_chat(-100123, kb)
    data = json.loads(group_kb.to_json())
    assert all("web_app" not in b for row in data["inline_keyboard"] for b in row)
    assert bot.for_chat(-100123, bot.main_keyboard("ru")) is None
    assert bot.for_chat(555, kb) is kb  # в личке ничего не меняем
    only_webapp = bot.tz_markup("ru")
    assert bot.for_chat(-1, only_webapp) is not None  # кнопка «Всё верно» остаётся


def test_has_pending():
    import tools
    assert not tools.has_pending(-777)
    tools.set_pending(-777, "alert", "bitcoin")
    assert tools.has_pending(-777)
    tools.pop_pending(-777)
    assert not tools.has_pending(-777)
