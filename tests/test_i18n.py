"""Каждый язык из settings.LANGS должен быть во ВСЕХ словарях переводов, с теми же ключами
и теми же плейсхолдерами {…}, что и английский. Иначе у пользователя этого языка — KeyError."""
import re
import string

import pytest

import settings as S

LANGS = S.LANGS


def dicts():
    import bot
    import chart
    import game
    import help_texts
    import market as M
    import social
    import tools
    return {
        "bot.T": bot.T, "bot.PROF": bot.PROF, "bot.CMD_DESC": bot.CMD_DESC, "game.GT": game.GT,
        "tools.TT": tools.TT, "social.ST": social.ST, "chart.CT": chart.CT, "help.HELP": help_texts.HELP,
        "help.GROUP": help_texts.GROUP_SETTINGS, "help.DESC": help_texts.DESCRIPTION,
        "help.SHORT": help_texts.SHORT_DESCRIPTION, "M.LABELS": M.LABELS, "M.MOOD": M.MOOD,
        "M.WEEK_MOOD": M.WEEK_MOOD, "M.FNG_CLASS": M.FNG_CLASS, "M.FALLBACK_AI": M.FALLBACK_AI,
        "M.FALLBACK_FACTS": M.FALLBACK_FACTS, "M.LANG_NAMES": M.LANG_NAMES,
    }


def placeholders(text):
    return sorted({f[1] for f in string.Formatter().parse(text) if f[1]})


@pytest.mark.parametrize("name", list(dicts()))
def test_every_language_everywhere(name):
    d = dicts()[name]
    assert set(LANGS) <= set(d), (name, set(LANGS) - set(d))
    en = d["en"]
    for lang in LANGS:
        v = d[lang]
        if isinstance(en, dict):
            if not en:  # FNG_CLASS: у английского свои названия, словарь пустой намеренно
                assert lang == "en" or v, (name, lang)
                continue
            assert set(v) == set(en), (name, lang, set(en) ^ set(v))
            for k, txt in en.items():
                if isinstance(txt, str):
                    assert placeholders(v[k]) == placeholders(txt), (name, lang, k)
        elif isinstance(en, (list, tuple)):
            if name != "M.FALLBACK_FACTS":
                assert len(v) == len(en), (name, lang)
        elif isinstance(en, str):
            assert placeholders(v) == placeholders(en), (name, lang)


def test_language_picker_and_detection():
    import bot
    import social
    assert [c for c, _ in bot.LANG_BUTTONS] == LANGS
    assert social.detect_lang("uk") == "uk"


def test_webapp_has_all_languages():
    html = open("webapp/index.html", encoding="utf-8").read()
    js_langs = re.search(r"const LANGS = \[(.*?)\];", html).group(1)
    assert re.findall(r"'(\w+)'", js_langs) == LANGS
    # все массивы переводов (5+ языков) теперь на len(LANGS) элементов
    for line in html.split("\n"):
        if re.match(r"^\s+\w+: \['", line):
            first = re.search(r"\[(.*?)\]", line).group(1)
            assert len(re.findall(r"'[^']*'", first)) == len(LANGS) or "open:" in line, line[:80]
