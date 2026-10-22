"""Игра «Вверх или вниз?»: прогноз цены монеты на 2 часа, баллы, серии, рейтинг."""
import html
import random

from telebot import types

import db
import market as M

HORIZON_H = 2  # фиксированный срок прогноза, часы
BASE_POINTS = 10


def score(streak: int) -> int:
    """10 баллов + бонус +2 за каждую победу в серии (максимум +10)."""
    return BASE_POINTS + min(streak, 5) * 2


GT = {
    "en": {
        "title": "🎯 <b>Up or Down?</b>", "coin": "Coin: <b>{sym}</b> · now {price}",
        "ask": "Where will the price be in 2 hours?",
        "hint": "Right call: +10 points, plus a streak bonus. A wrong call costs nothing. "
                "Your name is shown on the leaderboard; you can hide it in settings.",
        "up": "🚀 Up", "down": "🔻 Down", "next": "🔄 Another coin", "lb": "🏆 Leaderboard",
        "me": "📊 My stats", "again": "🎯 Play again",
        "placed": "✅ <b>Locked in!</b> {sym} {dir} in 2 h (from {price}).\nI'll message you with the result.",
        "dir_up": "UP 🚀", "dir_down": "DOWN 🔻",
        "limit": "⏳ You already have {n} open predictions. Wait for a result first!",
        "dup": "You already have an open prediction on {sym}. Try another coin 🔄",
        "expired": "⌛ That card is out of date — here's a fresh one.",
        "win": "✅ <b>Nailed it!</b> {sym}: {p0} → {p1} ({chg})\n+{pts} points{streak}",
        "loss": "❌ <b>Not this time.</b> {sym}: {p0} → {p1} ({chg})\nStreak reset — shake it off 💪",
        "draw": "🤝 <b>Draw.</b> {sym} barely moved ({p0} → {p1}). No points either way.",
        "streak": " · streak {n} 🔥",
        "lb_week": "🏆 <b>Top players — this week</b>", "lb_all": "🏆 <b>Top players — all time</b>",
        "lb_you": "You: #{rank} · {pts} pts", "lb_empty": "No players yet — be the first! 🎯",
        "btn_week": "📅 This week", "btn_all": "🌍 All time",
        "stats": "📊 <b>Your stats</b>\nPoints: {pts} (this week: {wp})\nWins: {w} · Losses: {l}\n"
                 "Streak: {s} (best: {b})\nOpen predictions: {o}",
        "stats_none": "You haven't played yet. Make your first call! 🎯",
        "weekly_line": "🎯 Game this week: <b>{pts}</b> pts · rank #{rank}", "anon": "Player {n}",
    },
    "ru": {
        "title": "🎯 <b>Вверх или вниз?</b>", "coin": "Монета: <b>{sym}</b> · сейчас {price}",
        "ask": "Где будет цена через 2 часа?",
        "hint": "Угадал: +10 баллов, плюс бонус за серию. Ошибка ничего не стоит. "
                "Ваше имя видно в рейтинге, скрыть можно в настройках.",
        "up": "🚀 Вверх", "down": "🔻 Вниз", "next": "🔄 Другая монета", "lb": "🏆 Рейтинг",
        "me": "📊 Моя статистика", "again": "🎯 Сыграть ещё",
        "placed": "✅ <b>Прогноз принят!</b> {sym} {dir} через 2 ч (от {price}).\nНапишу, как только узнаем результат.",
        "dir_up": "ВВЕРХ 🚀", "dir_down": "ВНИЗ 🔻",
        "limit": "⏳ У вас уже {n} открытых прогноза. Дождитесь результата!",
        "dup": "У вас уже есть открытый прогноз по {sym}. Попробуйте другую монету 🔄",
        "expired": "⌛ Эта карточка устарела — вот новая.",
        "win": "✅ <b>В точку!</b> {sym}: {p0} → {p1} ({chg})\n+{pts} баллов{streak}",
        "loss": "❌ <b>В этот раз мимо.</b> {sym}: {p0} → {p1} ({chg})\nСерия сброшена — не беда 💪",
        "draw": "🤝 <b>Ничья.</b> {sym} почти не двинулась ({p0} → {p1}). Баллов нет.",
        "streak": " · серия {n} 🔥",
        "lb_week": "🏆 <b>Лучшие игроки — эта неделя</b>", "lb_all": "🏆 <b>Лучшие игроки — за всё время</b>",
        "lb_you": "Вы: #{rank} · {pts} баллов", "lb_empty": "Игроков пока нет — станьте первым! 🎯",
        "btn_week": "📅 Неделя", "btn_all": "🌍 Всё время",
        "stats": "📊 <b>Ваша статистика</b>\nБаллы: {pts} (за неделю: {wp})\nПобед: {w} · Поражений: {l}\n"
                 "Серия: {s} (рекорд: {b})\nОткрытых прогнозов: {o}",
        "stats_none": "Вы ещё не играли. Сделайте первый прогноз! 🎯",
        "weekly_line": "🎯 Игра на этой неделе: <b>{pts}</b> баллов · место #{rank}", "anon": "Игрок {n}",
    },
    "fr": {
        "title": "🎯 <b>Hausse ou baisse ?</b>", "coin": "Crypto : <b>{sym}</b> · actuellement {price}",
        "ask": "Où sera le cours dans 2 heures ?",
        "hint": "Bon pronostic : +10 points, plus un bonus de série. Un mauvais pronostic ne coûte rien. "
                "Votre nom apparaît au classement ; vous pouvez le masquer dans les paramètres.",
        "up": "🚀 Hausse", "down": "🔻 Baisse", "next": "🔄 Autre crypto", "lb": "🏆 Classement",
        "me": "📊 Mes stats", "again": "🎯 Rejouer",
        "placed": "✅ <b>Pronostic enregistré !</b> {sym} {dir} dans 2 h (depuis {price}).\nJe vous écris avec le résultat.",
        "dir_up": "HAUSSE 🚀", "dir_down": "BAISSE 🔻",
        "limit": "⏳ Vous avez déjà {n} pronostics en cours. Attendez un résultat !",
        "dup": "Vous avez déjà un pronostic en cours sur {sym}. Essayez une autre crypto 🔄",
        "expired": "⌛ Cette carte est périmée — en voici une nouvelle.",
        "win": "✅ <b>Bien joué !</b> {sym} : {p0} → {p1} ({chg})\n+{pts} points{streak}",
        "loss": "❌ <b>Pas cette fois.</b> {sym} : {p0} → {p1} ({chg})\nSérie remise à zéro — on repart 💪",
        "draw": "🤝 <b>Égalité.</b> {sym} a à peine bougé ({p0} → {p1}). Aucun point.",
        "streak": " · série {n} 🔥",
        "lb_week": "🏆 <b>Meilleurs joueurs — cette semaine</b>", "lb_all": "🏆 <b>Meilleurs joueurs — de tous les temps</b>",
        "lb_you": "Vous : n°{rank} · {pts} pts", "lb_empty": "Aucun joueur pour l’instant — soyez le premier ! 🎯",
        "btn_week": "📅 Cette semaine", "btn_all": "🌍 Tout le temps",
        "stats": "📊 <b>Vos stats</b>\nPoints : {pts} (cette semaine : {wp})\nVictoires : {w} · Défaites : {l}\n"
                 "Série : {s} (record : {b})\nPronostics en cours : {o}",
        "stats_none": "Vous n’avez pas encore joué. Faites votre premier pronostic ! 🎯",
        "weekly_line": "🎯 Jeu cette semaine : <b>{pts}</b> pts · n°{rank}", "anon": "Joueur {n}",
    },
    "es": {
        "title": "🎯 <b>¿Sube o baja?</b>", "coin": "Moneda: <b>{sym}</b> · ahora {price}",
        "ask": "¿Dónde estará el precio dentro de 2 horas?",
        "hint": "Acierto: +10 puntos, más bonus de racha. Fallar no cuesta nada. "
                "Tu nombre aparece en la clasificación; puedes ocultarlo en los ajustes.",
        "up": "🚀 Sube", "down": "🔻 Baja", "next": "🔄 Otra moneda", "lb": "🏆 Clasificación",
        "me": "📊 Mis stats", "again": "🎯 Jugar otra vez",
        "placed": "✅ <b>¡Apuesta hecha!</b> {sym} {dir} en 2 h (desde {price}).\nTe escribiré con el resultado.",
        "dir_up": "SUBE 🚀", "dir_down": "BAJA 🔻",
        "limit": "⏳ Ya tienes {n} predicciones abiertas. ¡Espera un resultado!",
        "dup": "Ya tienes una predicción abierta sobre {sym}. Prueba otra moneda 🔄",
        "expired": "⌛ Esa tarjeta caducó — aquí tienes una nueva.",
        "win": "✅ <b>¡Acertaste!</b> {sym}: {p0} → {p1} ({chg})\n+{pts} puntos{streak}",
        "loss": "❌ <b>Esta vez no.</b> {sym}: {p0} → {p1} ({chg})\nRacha reiniciada — ¡ánimo! 💪",
        "draw": "🤝 <b>Empate.</b> {sym} casi no se movió ({p0} → {p1}). Sin puntos.",
        "streak": " · racha {n} 🔥",
        "lb_week": "🏆 <b>Mejores jugadores — esta semana</b>", "lb_all": "🏆 <b>Mejores jugadores — de siempre</b>",
        "lb_you": "Tú: n.º {rank} · {pts} pts", "lb_empty": "Aún no hay jugadores — ¡sé el primero! 🎯",
        "btn_week": "📅 Esta semana", "btn_all": "🌍 Siempre",
        "stats": "📊 <b>Tus stats</b>\nPuntos: {pts} (esta semana: {wp})\nVictorias: {w} · Derrotas: {l}\n"
                 "Racha: {s} (mejor: {b})\nPredicciones abiertas: {o}",
        "stats_none": "Aún no has jugado. ¡Haz tu primera predicción! 🎯",
        "weekly_line": "🎯 Juego esta semana: <b>{pts}</b> pts · n.º {rank}", "anon": "Jugador {n}",
    },
    "de": {
        "title": "🎯 <b>Hoch oder runter?</b>", "coin": "Coin: <b>{sym}</b> · aktuell {price}",
        "ask": "Wo steht der Kurs in 2 Stunden?",
        "hint": "Richtig getippt: +10 Punkte plus Serienbonus. Falsch tippen kostet nichts. "
                "Ihr Name erscheint in der Rangliste; in den Einstellungen können Sie ihn ausblenden.",
        "up": "🚀 Hoch", "down": "🔻 Runter", "next": "🔄 Anderer Coin", "lb": "🏆 Rangliste",
        "me": "📊 Meine Stats", "again": "🎯 Nochmal spielen",
        "placed": "✅ <b>Tipp gespeichert!</b> {sym} {dir} in 2 Std. (ab {price}).\nIch melde mich mit dem Ergebnis.",
        "dir_up": "HOCH 🚀", "dir_down": "RUNTER 🔻",
        "limit": "⏳ Sie haben schon {n} offene Tipps. Warten Sie auf ein Ergebnis!",
        "dup": "Sie haben schon einen offenen Tipp auf {sym}. Probieren Sie einen anderen Coin 🔄",
        "expired": "⌛ Diese Karte ist veraltet — hier eine neue.",
        "win": "✅ <b>Treffer!</b> {sym}: {p0} → {p1} ({chg})\n+{pts} Punkte{streak}",
        "loss": "❌ <b>Diesmal nicht.</b> {sym}: {p0} → {p1} ({chg})\nSerie zurückgesetzt — weiter geht’s 💪",
        "draw": "🤝 <b>Unentschieden.</b> {sym} hat sich kaum bewegt ({p0} → {p1}). Keine Punkte.",
        "streak": " · Serie {n} 🔥",
        "lb_week": "🏆 <b>Beste Spieler — diese Woche</b>", "lb_all": "🏆 <b>Beste Spieler — gesamt</b>",
        "lb_you": "Sie: Platz {rank} · {pts} Pkt.", "lb_empty": "Noch keine Spieler — seien Sie der Erste! 🎯",
        "btn_week": "📅 Diese Woche", "btn_all": "🌍 Gesamt",
        "stats": "📊 <b>Ihre Stats</b>\nPunkte: {pts} (diese Woche: {wp})\nSiege: {w} · Niederlagen: {l}\n"
                 "Serie: {s} (Rekord: {b})\nOffene Tipps: {o}",
        "stats_none": "Sie haben noch nicht gespielt. Geben Sie Ihren ersten Tipp ab! 🎯",
        "weekly_line": "🎯 Spiel diese Woche: <b>{pts}</b> Pkt. · Platz {rank}", "anon": "Spieler {n}",
    },
}


def _coins() -> list:
    """Монеты для игры: топ-50 по капитализации без стейблкоинов."""
    return M._pool(M.get_markets("usd"))[:50]


def after_markup(lang: str) -> types.InlineKeyboardMarkup:
    g = GT[lang]
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton(g["again"], callback_data="g:new"),
           types.InlineKeyboardButton(g["lb"], callback_data="g:lb:w"))
    return kb


def new_card(lang: str, exclude: str = None) -> tuple:
    """Карточка раунда со случайной монетой: (текст, кнопки)."""
    g = GT[lang]
    coins = _coins()
    coin = random.choice([c for c in coins if c["id"] != exclude] or coins)
    sym = html.escape(coin["symbol"].upper())
    text = (f"{g['title']}\n\n{g['coin'].format(sym=sym, price=M.fmt_price(coin['current_price'], 'usd'))}\n"
            f"{g['ask']}\n\n{g['hint']}")
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton(g["up"], callback_data=f"g:p:{coin['id']}:u"),
           types.InlineKeyboardButton(g["down"], callback_data=f"g:p:{coin['id']}:d"))
    kb.row(types.InlineKeyboardButton(g["next"], callback_data=f"g:next:{coin['id']}"))
    kb.row(types.InlineKeyboardButton(g["lb"], callback_data="g:lb:w"),
           types.InlineKeyboardButton(g["me"], callback_data="g:me"))
    return text, kb


def place(chat_id: int, lang: str, coin_id: str, direction: str) -> tuple:
    """Принимает прогноз на 2 часа. Возвращает (текст, кнопки, ok)."""
    g = GT[lang]
    coin = next((c for c in _coins() if c["id"] == coin_id), None)
    if coin is None or direction not in ("u", "d"):
        text, kb = new_card(lang)
        return f"{g['expired']}\n\n{text}", kb, False
    sym = html.escape(coin["symbol"].upper())
    open_preds = db.game_open_predictions(chat_id)
    if len(open_preds) >= db.GAME_OPEN_LIMIT:
        return g["limit"].format(n=len(open_preds)), after_markup(lang), False
    if any(cid == coin_id for cid, _ in open_preds):
        return g["dup"].format(sym=sym), after_markup(lang), False
    db.game_create(chat_id, coin_id, coin["symbol"].upper(), 1 if direction == "u" else -1,
                   HORIZON_H, coin["current_price"])
    text = g["placed"].format(sym=sym, dir=g["dir_up"] if direction == "u" else g["dir_down"],
                              price=M.fmt_price(coin["current_price"], "usd"))
    return text, after_markup(lang), True


def result_text(r: dict) -> str:
    g = GT[r["lang"]]
    base = dict(sym=html.escape(r["symbol"]), p0=M.fmt_price(r["p0"], "usd"), p1=M.fmt_price(r["p1"], "usd"),
                chg=f"{r['change']:+.2f}%")
    if r["outcome"] == "win":
        streak = g["streak"].format(n=r["streak"]) if r["streak"] >= 2 else ""
        return g["win"].format(pts=r["points"], streak=streak, **base)
    return g["loss" if r["outcome"] == "loss" else "draw"].format(**base)


def _name(lang: str, chat_id: int, first_name, hidden: bool) -> str:
    if hidden or not first_name:
        return GT[lang]["anon"].format(n=abs(chat_id) % 10000)
    return html.escape(first_name[:14])


def leaderboard(lang: str, chat_id: int, scope: str) -> tuple:
    g = GT[lang]
    rows, mine = db.game_leaderboard(scope, chat_id)
    lines = [g["lb_week" if scope == "week" else "lb_all"]]
    medals = ["🥇", "🥈", "🥉"]
    if not rows:
        lines.append("\n" + g["lb_empty"])
    for i, (cid, first_name, hidden, pts) in enumerate(rows):
        mark = medals[i] if i < 3 else M.keycap(i + 1)
        me = " ◀" if cid == chat_id else ""
        lines.append(f"{mark} {_name(lang, cid, first_name, hidden)} — <b>{pts}</b>{me}")
    if mine and not any(r[0] == chat_id for r in rows):
        lines.append("…\n" + g["lb_you"].format(rank=mine[0], pts=mine[1]))
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton(g["btn_week"], callback_data="g:lbt:w"),
           types.InlineKeyboardButton(g["btn_all"], callback_data="g:lbt:a"))
    kb.row(types.InlineKeyboardButton(g["again"], callback_data="g:new"))
    return "\n".join(lines), kb


def stats(lang: str, chat_id: int) -> tuple:
    g = GT[lang]
    p = db.game_player(chat_id)
    if p is None or (p["wins"] + p["losses"] == 0 and not p["open"]):
        return g["stats_none"], after_markup(lang)
    return (g["stats"].format(pts=p["points"], wp=p["week_points"], w=p["wins"], l=p["losses"],
                              s=p["streak"], b=p["best_streak"], o=p["open"]), after_markup(lang))


def weekly_line(chat_id: int, lang: str):
    info = db.game_week_info(chat_id)
    if not info:
        return None
    return GT[lang]["weekly_line"].format(rank=info[0], pts=info[1])
