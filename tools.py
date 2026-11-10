"""Инструменты пользователя: карточка монеты, ценовые алерты, портфель.
Все тексты на 5 языках; данные берутся из кэша курсов (market.get_markets)."""
import html
import re
import threading
import time

from telebot import types

import db
import market as M

ALERT_LIMIT = 10
PF_LIMIT = 30
PENDING_TTL = 600  # сек: сколько ждём ответ на вопрос «введите цену/количество»

# Популярные народные названия → id CoinGecko
ALIASES = {
    "биткоин": "bitcoin", "биткойн": "bitcoin", "биток": "bitcoin", "битко": "bitcoin", "бтс": "bitcoin",
    "btc": "bitcoin", "xbt": "bitcoin", "эфир": "ethereum", "эфириум": "ethereum", "етериум": "ethereum",
    "eth": "ethereum", "ether": "ethereum", "тон": "the-open-network", "toncoin": "the-open-network",
    "солана": "solana", "сол": "solana", "доге": "dogecoin", "додж": "dogecoin", "догикоин": "dogecoin",
    "рипл": "ripple", "xrp": "ripple", "тезер": "tether", "тетер": "tether", "usdt": "tether",
    "кардано": "cardano", "лайткоин": "litecoin", "пепе": "pepe", "шиба": "shiba-inu", "трон": "tron",
    "бнб": "binancecoin", "bnb": "binancecoin",
}

TT = {
    "en": {
        "rank": "rank #{n}", "range": "24h range", "mcap": "Market cap", "vol": "Volume 24h",
        "ath": "All-time high", "hold": "💼 You hold {amt} {sym} ≈ <b>{val}</b>",
        "alerts_on": "🔔 Active alerts: {n}", "updated": "Updated {t}",
        "btn_alert": "🔔 Price alert", "btn_pf": "💼 Portfolio", "btn_fav_add": "⭐ To My coins",
        "btn_fav_del": "✖️ From My coins", "btn_game": "🎯 Predict", "btn_refresh": "🔄", "btn_share": "📤 Share",
        "not_found": "🤔 I don't know “{q}”. Send a ticker or name from the top 200, e.g. <b>BTC</b>, <b>ETH</b> or <b>solana</b>.",
        "unknown": "🤖 Send a coin ticker (e.g. <b>BTC</b>) to get its card, or /help to see everything I can do.",
        "alert_pick": "🔔 <b>Price alert for {sym}</b>\nNow: <b>{price}</b>\n\nPick a level or tap “✏️ My price”:",
        "btn_custom": "✏️ My price",
        "ask_price": "✏️ Send the target price for <b>{sym}</b> in {cur} (now {price}).\nExample: <code>{ex}</code>",
        "alert_set": "✅ Done! I'll message you when <b>{sym}</b> goes {dir} <b>{target}</b> (now {price}).",
        "above": "above", "below": "below",
        "alert_limit": "⚠️ You already have {n} active alerts — the maximum. Delete one in /alerts.",
        "alert_dup": "You already have this alert 👍",
        "alert_same": "🤔 That's the current price — pick a level above or below it.",
        "bad_number": "🤔 That doesn't look like a number. Example: <code>{ex}</code>",
        "alerts_title": "🔔 <b>Your price alerts</b>",
        "alerts_empty": "🔔 You have no price alerts yet.\n\nSend a ticker (e.g. <b>BTC</b>) and tap “🔔 Price alert” — or type <code>/alert BTC 100000</code>.",
        "alerts_hint": "Tap ✖️ to delete an alert.",
        "alert_hit_up": "🚀 <b>{sym} is above {target}!</b>", "alert_hit_down": "📉 <b>{sym} dropped below {target}!</b>",
        "alert_now": "Now: <b>{price}</b> ({chg} · 24h)",
        "deleted": "Deleted", "usage_alert": "Usage: <code>/alert BTC 100000</code>",
        "pf_title": "💼 <b>Your portfolio</b>", "pf_total": "Total: <b>{val}</b>\n24h: {chg}",
        "pf_empty": "💼 Your portfolio is empty.\n\nAdd a coin: <code>/add BTC 0.5</code> — or send a ticker and tap “💼 Portfolio”.",
        "pf_ask": "💼 How much <b>{sym}</b> do you hold? Send a number, e.g. <code>0.5</code>.\nSend <code>0</code> to remove it.",
        "pf_add_ask": "➕ Send the coin and amount, e.g. <code>BTC 0.5</code>",
        "pf_saved": "✅ Saved: {amt} {sym} ≈ <b>{val}</b>", "pf_removed": "🗑 {sym} removed from your portfolio.",
        "pf_limit": "⚠️ Up to {n} coins in the portfolio.", "pf_usage": "Usage: <code>/add BTC 0.5</code> (0 removes the coin)",
        "btn_pf_add": "➕ Add coin", "btn_pf_edit": "✏️ {sym}",
        "pf_short": "💼 Portfolio: <b>{val}</b> · 24h: {chg}", "pf_week": "💼 Portfolio over the week: <b>{val}</b> · {chg}",
        "pf_note": "Prices in {cur}. Change the currency in ⚙️ Settings.",
        "fav_added": "⭐ Added to My coins", "fav_added_hint": "⭐ Added! Turn on “What to show → My coins” in settings to see them in reports.",
        "fav_removed": "Removed from My coins", "fav_full": "My coins is full (10)",
        "cancelled": "👌 Cancelled.", "placeholder_price": "e.g. {ex}", "placeholder_amount": "e.g. 0.5",
        "price_usage": "Send a ticker, e.g. <code>/price BTC</code> — or just <b>BTC</b>.",
    },
    "ru": {
        "rank": "место #{n}", "range": "Диапазон 24ч", "mcap": "Капитализация", "vol": "Объём 24ч",
        "ath": "Исторический максимум", "hold": "💼 У вас {amt} {sym} ≈ <b>{val}</b>",
        "alerts_on": "🔔 Активных алертов: {n}", "updated": "Обновлено {t}",
        "btn_alert": "🔔 Алерт на цену", "btn_pf": "💼 Портфель", "btn_fav_add": "⭐ В мои монеты",
        "btn_fav_del": "✖️ Из моих монет", "btn_game": "🎯 Прогноз", "btn_refresh": "🔄", "btn_share": "📤 Поделиться",
        "not_found": "🤔 Не знаю монету «{q}». Отправьте тикер или название из топ-200, например <b>BTC</b>, <b>ETH</b> или <b>solana</b>.",
        "unknown": "🤖 Отправьте тикер монеты (например, <b>BTC</b>), чтобы получить её карточку, или /help — всё, что я умею.",
        "alert_pick": "🔔 <b>Алерт на цену {sym}</b>\nСейчас: <b>{price}</b>\n\nВыберите уровень или нажмите «✏️ Своя цена»:",
        "btn_custom": "✏️ Своя цена",
        "ask_price": "✏️ Отправьте целевую цену <b>{sym}</b> в {cur} (сейчас {price}).\nНапример: <code>{ex}</code>",
        "alert_set": "✅ Готово! Напишу, когда <b>{sym}</b> будет {dir} <b>{target}</b> (сейчас {price}).",
        "above": "выше", "below": "ниже",
        "alert_limit": "⚠️ У вас уже {n} активных алертов — это максимум. Удалите лишний в /alerts.",
        "alert_dup": "Такой алерт уже есть 👍",
        "alert_same": "🤔 Это текущая цена — выберите уровень выше или ниже.",
        "bad_number": "🤔 Не похоже на число. Например: <code>{ex}</code>",
        "alerts_title": "🔔 <b>Ваши ценовые алерты</b>",
        "alerts_empty": "🔔 Ценовых алертов пока нет.\n\nОтправьте тикер (например, <b>BTC</b>) и нажмите «🔔 Алерт на цену» — или напишите <code>/alert BTC 100000</code>.",
        "alerts_hint": "Нажмите ✖️, чтобы удалить алерт.",
        "alert_hit_up": "🚀 <b>{sym} выше {target}!</b>", "alert_hit_down": "📉 <b>{sym} опустилась ниже {target}!</b>",
        "alert_now": "Сейчас: <b>{price}</b> ({chg} · 24ч)",
        "deleted": "Удалено", "usage_alert": "Формат: <code>/alert BTC 100000</code>",
        "pf_title": "💼 <b>Ваш портфель</b>", "pf_total": "Итого: <b>{val}</b>\nЗа 24ч: {chg}",
        "pf_empty": "💼 Портфель пуст.\n\nДобавьте монету: <code>/add BTC 0.5</code> — или отправьте тикер и нажмите «💼 Портфель».",
        "pf_ask": "💼 Сколько у вас <b>{sym}</b>? Отправьте число, например <code>0.5</code>.\nОтправьте <code>0</code>, чтобы убрать монету.",
        "pf_add_ask": "➕ Отправьте монету и количество, например <code>BTC 0.5</code>",
        "pf_saved": "✅ Сохранено: {amt} {sym} ≈ <b>{val}</b>", "pf_removed": "🗑 {sym} убрана из портфеля.",
        "pf_limit": "⚠️ В портфеле может быть до {n} монет.", "pf_usage": "Формат: <code>/add BTC 0.5</code> (0 — убрать монету)",
        "btn_pf_add": "➕ Добавить", "btn_pf_edit": "✏️ {sym}",
        "pf_short": "💼 Портфель: <b>{val}</b> · 24ч: {chg}", "pf_week": "💼 Портфель за неделю: <b>{val}</b> · {chg}",
        "pf_note": "Цены в {cur}. Валюту можно сменить в ⚙️ Настройках.",
        "fav_added": "⭐ Добавлено в мои монеты", "fav_added_hint": "⭐ Добавлено! Включите «Что показывать → Мои монеты» в настройках, чтобы видеть их в отчётах.",
        "fav_removed": "Убрано из моих монет", "fav_full": "В «Моих монетах» уже 10 монет",
        "cancelled": "👌 Отменено.", "placeholder_price": "например, {ex}", "placeholder_amount": "например, 0.5",
        "price_usage": "Отправьте тикер, например <code>/price BTC</code> — или просто <b>BTC</b>.",
    },
    "fr": {
        "rank": "rang n°{n}", "range": "Fourchette 24 h", "mcap": "Capitalisation", "vol": "Volume 24 h",
        "ath": "Record historique", "hold": "💼 Vous détenez {amt} {sym} ≈ <b>{val}</b>",
        "alerts_on": "🔔 Alertes actives : {n}", "updated": "Mis à jour {t}",
        "btn_alert": "🔔 Alerte de prix", "btn_pf": "💼 Portefeuille", "btn_fav_add": "⭐ Dans Mes cryptos",
        "btn_fav_del": "✖️ Retirer de Mes cryptos", "btn_game": "🎯 Pronostic", "btn_refresh": "🔄", "btn_share": "📤 Partager",
        "not_found": "🤔 Je ne connais pas « {q} ». Envoyez un ticker ou un nom du top 200, par ex. <b>BTC</b>, <b>ETH</b> ou <b>solana</b>.",
        "unknown": "🤖 Envoyez un ticker (par ex. <b>BTC</b>) pour voir sa fiche, ou /help pour tout ce que je sais faire.",
        "alert_pick": "🔔 <b>Alerte de prix pour {sym}</b>\nActuellement : <b>{price}</b>\n\nChoisissez un niveau ou touchez « ✏️ Mon prix » :",
        "btn_custom": "✏️ Mon prix",
        "ask_price": "✏️ Envoyez le prix cible de <b>{sym}</b> en {cur} (actuellement {price}).\nExemple : <code>{ex}</code>",
        "alert_set": "✅ C’est noté ! Je vous écris quand <b>{sym}</b> passera {dir} <b>{target}</b> (actuellement {price}).",
        "above": "au-dessus de", "below": "sous",
        "alert_limit": "⚠️ Vous avez déjà {n} alertes actives — c’est le maximum. Supprimez-en une dans /alerts.",
        "alert_dup": "Cette alerte existe déjà 👍",
        "alert_same": "🤔 C’est le prix actuel — choisissez un niveau au-dessus ou en dessous.",
        "bad_number": "🤔 Ce n’est pas un nombre. Exemple : <code>{ex}</code>",
        "alerts_title": "🔔 <b>Vos alertes de prix</b>",
        "alerts_empty": "🔔 Aucune alerte de prix pour l’instant.\n\nEnvoyez un ticker (par ex. <b>BTC</b>) et touchez « 🔔 Alerte de prix » — ou tapez <code>/alert BTC 100000</code>.",
        "alerts_hint": "Touchez ✖️ pour supprimer une alerte.",
        "alert_hit_up": "🚀 <b>{sym} dépasse {target} !</b>", "alert_hit_down": "📉 <b>{sym} est passé sous {target} !</b>",
        "alert_now": "Actuellement : <b>{price}</b> ({chg} · 24 h)",
        "deleted": "Supprimé", "usage_alert": "Format : <code>/alert BTC 100000</code>",
        "pf_title": "💼 <b>Votre portefeuille</b>", "pf_total": "Total : <b>{val}</b>\n24 h : {chg}",
        "pf_empty": "💼 Votre portefeuille est vide.\n\nAjoutez une crypto : <code>/add BTC 0.5</code> — ou envoyez un ticker et touchez « 💼 Portefeuille ».",
        "pf_ask": "💼 Combien de <b>{sym}</b> détenez-vous ? Envoyez un nombre, par ex. <code>0.5</code>.\nEnvoyez <code>0</code> pour la retirer.",
        "pf_add_ask": "➕ Envoyez la crypto et la quantité, par ex. <code>BTC 0.5</code>",
        "pf_saved": "✅ Enregistré : {amt} {sym} ≈ <b>{val}</b>", "pf_removed": "🗑 {sym} retiré du portefeuille.",
        "pf_limit": "⚠️ Jusqu’à {n} cryptos dans le portefeuille.", "pf_usage": "Format : <code>/add BTC 0.5</code> (0 retire la crypto)",
        "btn_pf_add": "➕ Ajouter", "btn_pf_edit": "✏️ {sym}",
        "pf_short": "💼 Portefeuille : <b>{val}</b> · 24 h : {chg}", "pf_week": "💼 Portefeuille sur la semaine : <b>{val}</b> · {chg}",
        "pf_note": "Prix en {cur}. Changez la devise dans ⚙️ Paramètres.",
        "fav_added": "⭐ Ajouté à Mes cryptos", "fav_added_hint": "⭐ Ajouté ! Activez « Affichage → Mes cryptos » dans les paramètres pour les voir dans les envois.",
        "fav_removed": "Retiré de Mes cryptos", "fav_full": "Mes cryptos est plein (10)",
        "cancelled": "👌 Annulé.", "placeholder_price": "par ex. {ex}", "placeholder_amount": "par ex. 0.5",
        "price_usage": "Envoyez un ticker, par ex. <code>/price BTC</code> — ou simplement <b>BTC</b>.",
    },
    "es": {
        "rank": "puesto n.º {n}", "range": "Rango 24 h", "mcap": "Capitalización", "vol": "Volumen 24 h",
        "ath": "Máximo histórico", "hold": "💼 Tienes {amt} {sym} ≈ <b>{val}</b>",
        "alerts_on": "🔔 Alertas activas: {n}", "updated": "Actualizado {t}",
        "btn_alert": "🔔 Alerta de precio", "btn_pf": "💼 Cartera", "btn_fav_add": "⭐ A Mis monedas",
        "btn_fav_del": "✖️ Quitar de Mis monedas", "btn_game": "🎯 Predecir", "btn_refresh": "🔄", "btn_share": "📤 Compartir",
        "not_found": "🤔 No conozco «{q}». Envía un ticker o nombre del top 200, p. ej. <b>BTC</b>, <b>ETH</b> o <b>solana</b>.",
        "unknown": "🤖 Envía un ticker (p. ej. <b>BTC</b>) para ver su ficha, o /help para ver todo lo que sé hacer.",
        "alert_pick": "🔔 <b>Alerta de precio de {sym}</b>\nAhora: <b>{price}</b>\n\nElige un nivel o toca «✏️ Mi precio»:",
        "btn_custom": "✏️ Mi precio",
        "ask_price": "✏️ Envía el precio objetivo de <b>{sym}</b> en {cur} (ahora {price}).\nEjemplo: <code>{ex}</code>",
        "alert_set": "✅ ¡Listo! Te escribiré cuando <b>{sym}</b> esté {dir} <b>{target}</b> (ahora {price}).",
        "above": "por encima de", "below": "por debajo de",
        "alert_limit": "⚠️ Ya tienes {n} alertas activas — es el máximo. Borra alguna en /alerts.",
        "alert_dup": "Ya tienes esta alerta 👍",
        "alert_same": "🤔 Ese es el precio actual — elige un nivel por encima o por debajo.",
        "bad_number": "🤔 Eso no parece un número. Ejemplo: <code>{ex}</code>",
        "alerts_title": "🔔 <b>Tus alertas de precio</b>",
        "alerts_empty": "🔔 Aún no tienes alertas de precio.\n\nEnvía un ticker (p. ej. <b>BTC</b>) y toca «🔔 Alerta de precio» — o escribe <code>/alert BTC 100000</code>.",
        "alerts_hint": "Toca ✖️ para borrar una alerta.",
        "alert_hit_up": "🚀 <b>¡{sym} supera {target}!</b>", "alert_hit_down": "📉 <b>¡{sym} bajó de {target}!</b>",
        "alert_now": "Ahora: <b>{price}</b> ({chg} · 24 h)",
        "deleted": "Borrado", "usage_alert": "Formato: <code>/alert BTC 100000</code>",
        "pf_title": "💼 <b>Tu cartera</b>", "pf_total": "Total: <b>{val}</b>\n24 h: {chg}",
        "pf_empty": "💼 Tu cartera está vacía.\n\nAñade una moneda: <code>/add BTC 0.5</code> — o envía un ticker y toca «💼 Cartera».",
        "pf_ask": "💼 ¿Cuánto <b>{sym}</b> tienes? Envía un número, p. ej. <code>0.5</code>.\nEnvía <code>0</code> para quitarla.",
        "pf_add_ask": "➕ Envía la moneda y la cantidad, p. ej. <code>BTC 0.5</code>",
        "pf_saved": "✅ Guardado: {amt} {sym} ≈ <b>{val}</b>", "pf_removed": "🗑 {sym} quitada de tu cartera.",
        "pf_limit": "⚠️ Hasta {n} monedas en la cartera.", "pf_usage": "Formato: <code>/add BTC 0.5</code> (0 quita la moneda)",
        "btn_pf_add": "➕ Añadir", "btn_pf_edit": "✏️ {sym}",
        "pf_short": "💼 Cartera: <b>{val}</b> · 24 h: {chg}", "pf_week": "💼 Cartera en la semana: <b>{val}</b> · {chg}",
        "pf_note": "Precios en {cur}. Cambia la moneda en ⚙️ Ajustes.",
        "fav_added": "⭐ Añadida a Mis monedas", "fav_added_hint": "⭐ ¡Añadida! Activa «Qué mostrar → Mis monedas» en los ajustes para verlas en los envíos.",
        "fav_removed": "Quitada de Mis monedas", "fav_full": "Mis monedas está lleno (10)",
        "cancelled": "👌 Cancelado.", "placeholder_price": "p. ej. {ex}", "placeholder_amount": "p. ej. 0.5",
        "price_usage": "Envía un ticker, p. ej. <code>/price BTC</code> — o simplemente <b>BTC</b>.",
    },
    "de": {
        "rank": "Platz {n}", "range": "Spanne 24 Std.", "mcap": "Marktkapitalisierung", "vol": "Volumen 24 Std.",
        "ath": "Allzeithoch", "hold": "💼 Sie halten {amt} {sym} ≈ <b>{val}</b>",
        "alerts_on": "🔔 Aktive Alarme: {n}", "updated": "Aktualisiert {t}",
        "btn_alert": "🔔 Preisalarm", "btn_pf": "💼 Portfolio", "btn_fav_add": "⭐ Zu Meine Coins",
        "btn_fav_del": "✖️ Aus Meine Coins", "btn_game": "🎯 Tippen", "btn_refresh": "🔄", "btn_share": "📤 Teilen",
        "not_found": "🤔 „{q}“ kenne ich nicht. Senden Sie einen Ticker oder Namen aus den Top 200, z. B. <b>BTC</b>, <b>ETH</b> oder <b>solana</b>.",
        "unknown": "🤖 Senden Sie einen Ticker (z. B. <b>BTC</b>) für die Coin-Karte oder /help für alle Funktionen.",
        "alert_pick": "🔔 <b>Preisalarm für {sym}</b>\nAktuell: <b>{price}</b>\n\nWählen Sie ein Niveau oder tippen Sie „✏️ Eigener Preis“:",
        "btn_custom": "✏️ Eigener Preis",
        "ask_price": "✏️ Senden Sie den Zielpreis für <b>{sym}</b> in {cur} (aktuell {price}).\nBeispiel: <code>{ex}</code>",
        "alert_set": "✅ Erledigt! Ich melde mich, wenn <b>{sym}</b> {dir} <b>{target}</b> liegt (aktuell {price}).",
        "above": "über", "below": "unter",
        "alert_limit": "⚠️ Sie haben schon {n} aktive Alarme — das Maximum. Löschen Sie einen in /alerts.",
        "alert_dup": "Diesen Alarm gibt es schon 👍",
        "alert_same": "🤔 Das ist der aktuelle Preis — wählen Sie ein Niveau darüber oder darunter.",
        "bad_number": "🤔 Das sieht nicht nach einer Zahl aus. Beispiel: <code>{ex}</code>",
        "alerts_title": "🔔 <b>Ihre Preisalarme</b>",
        "alerts_empty": "🔔 Noch keine Preisalarme.\n\nSenden Sie einen Ticker (z. B. <b>BTC</b>) und tippen Sie „🔔 Preisalarm“ — oder schreiben Sie <code>/alert BTC 100000</code>.",
        "alerts_hint": "Tippen Sie ✖️, um einen Alarm zu löschen.",
        "alert_hit_up": "🚀 <b>{sym} ist über {target}!</b>", "alert_hit_down": "📉 <b>{sym} ist unter {target} gefallen!</b>",
        "alert_now": "Aktuell: <b>{price}</b> ({chg} · 24 Std.)",
        "deleted": "Gelöscht", "usage_alert": "Format: <code>/alert BTC 100000</code>",
        "pf_title": "💼 <b>Ihr Portfolio</b>", "pf_total": "Gesamt: <b>{val}</b>\n24 Std.: {chg}",
        "pf_empty": "💼 Ihr Portfolio ist leer.\n\nCoin hinzufügen: <code>/add BTC 0.5</code> — oder Ticker senden und „💼 Portfolio“ tippen.",
        "pf_ask": "💼 Wie viel <b>{sym}</b> halten Sie? Senden Sie eine Zahl, z. B. <code>0.5</code>.\n<code>0</code> entfernt den Coin.",
        "pf_add_ask": "➕ Senden Sie Coin und Menge, z. B. <code>BTC 0.5</code>",
        "pf_saved": "✅ Gespeichert: {amt} {sym} ≈ <b>{val}</b>", "pf_removed": "🗑 {sym} aus dem Portfolio entfernt.",
        "pf_limit": "⚠️ Bis zu {n} Coins im Portfolio.", "pf_usage": "Format: <code>/add BTC 0.5</code> (0 entfernt den Coin)",
        "btn_pf_add": "➕ Hinzufügen", "btn_pf_edit": "✏️ {sym}",
        "pf_short": "💼 Portfolio: <b>{val}</b> · 24 Std.: {chg}", "pf_week": "💼 Portfolio in der Woche: <b>{val}</b> · {chg}",
        "pf_note": "Preise in {cur}. Die Währung ändern Sie in ⚙️ Einstellungen.",
        "fav_added": "⭐ Zu Meine Coins hinzugefügt", "fav_added_hint": "⭐ Hinzugefügt! Aktivieren Sie „Anzeige → Meine Coins“ in den Einstellungen, um sie in Berichten zu sehen.",
        "fav_removed": "Aus Meine Coins entfernt", "fav_full": "Meine Coins ist voll (10)",
        "cancelled": "👌 Abgebrochen.", "placeholder_price": "z. B. {ex}", "placeholder_amount": "z. B. 0.5",
        "price_usage": "Senden Sie einen Ticker, z. B. <code>/price BTC</code> — oder einfach <b>BTC</b>.",
    },
}


# ------------------------------------------------------------------
# Ожидание ввода (цена для алерта, количество для портфеля)
# ------------------------------------------------------------------
_pending: dict = {}
_pending_lock = threading.Lock()


def set_pending(chat_id: int, kind: str, coin_id: str = None) -> None:
    with _pending_lock:
        _pending[chat_id] = (kind, coin_id, time.time())
        if len(_pending) > 10000:
            now = time.time()
            for k in [k for k, v in _pending.items() if now - v[2] > PENDING_TTL]:
                _pending.pop(k, None)


def pop_pending(chat_id: int):
    with _pending_lock:
        item = _pending.pop(chat_id, None)
    if item and time.time() - item[2] <= PENDING_TTL:
        return item[0], item[1]
    return None


# ------------------------------------------------------------------
# Разбор ввода
# ------------------------------------------------------------------
def parse_number(text: str):
    """'100000', '100 000', '1,5', '$97.5k', '2м' -> float > 0 или None."""
    if not text:
        return None
    t = text.strip().lower().replace(" ", "").replace(" ", "").replace("_", "")
    t = re.sub(r"^[$€₽₴₸]|[$€₽₴₸]$", "", t)
    mult = 1.0
    if t and t[-1] in "kк":
        mult, t = 1e3, t[:-1]
    elif t and t[-1] in "mм":
        mult, t = 1e6, t[:-1]
    if "," in t and "." in t:
        t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", t) else t.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", t):
        return None
    value = float(t) * mult
    return value if 0 < value < 1e15 else None


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower().lstrip("$#/"))


def resolve(query: str, data: list = None):
    """Монета из топ-200 по тикеру, id, названию или народному названию. None, если не нашли."""
    q = _norm(query)
    if not q or len(q) > 40:
        return None
    data = data if data is not None else M.get_markets("usd")
    q = ALIASES.get(q, q)
    for c in data:  # данные отсортированы по капитализации: при совпадении тикеров берём крупнейшую
        if c["id"] == q:
            return c
    for c in data:
        if c["symbol"].lower() == q:
            return c
    for c in data:
        if (c.get("name") or "").lower() == q:
            return c
    return None


def search(query: str, data: list, limit: int = 5) -> list:
    """Поиск для inline-режима: точные совпадения, затем по началу тикера/названия."""
    q = _norm(query)
    if not q:
        return []
    exact = resolve(q, data)
    out = [exact] if exact else []
    for c in data:
        if len(out) >= limit:
            break
        if c in out:
            continue
        if c["symbol"].lower().startswith(q) or (c.get("name") or "").lower().startswith(q):
            out.append(c)
    return out


def fmt_amount(x: float) -> str:
    if x >= 1000:
        return f"{x:,.2f}".replace(",", " ").rstrip("0").rstrip(".")
    return f"{x:.8f}".rstrip("0").rstrip(".") or "0"


def _example(price: float) -> str:
    """Круглая цель для подсказки: ~+10% от текущей цены."""
    if not price:
        return "100"
    return fmt_amount(float(f"{price * 1.1:.2g}"))


def _coin_in(currency: str, coin_id: str):
    try:
        return next((c for c in M.get_markets(currency) if c["id"] == coin_id), None)
    except Exception:
        return None


# ------------------------------------------------------------------
# Карточка монеты
# ------------------------------------------------------------------
def card_text(coin: dict, lang: str, currency: str, holding: float = None, alerts_n: int = 0) -> str:
    tt = TT[lang]
    sym = coin["symbol"].upper()
    emoji = M.COIN_EMOJIS.get(sym, "🪙")
    name = html.escape(coin.get("name") or sym)
    lines = [f"{emoji} <b>{name}</b> ({html.escape(sym)})"
             + (f" · {tt['rank'].format(n=coin['market_cap_rank'])}" if coin.get("market_cap_rank") else ""),
             f"💵 <b>{M.fmt_price(coin.get('current_price'), currency)}</b>",
             f"1h {M.fmt_pct(coin.get('price_change_percentage_1h_in_currency'))}\n"
             f"24h {M.fmt_pct(coin.get('price_change_percentage_24h_in_currency'))}\n"
             f"7d {M.fmt_pct(coin.get('price_change_percentage_7d_in_currency'))}"]
    extra = []
    if coin.get("low_24h") is not None and coin.get("high_24h") is not None:
        extra.append(f"📊 {tt['range']}: {M.fmt_price(coin['low_24h'], currency)} — "
                     f"{M.fmt_price(coin['high_24h'], currency)}")
    if coin.get("market_cap"):
        extra.append(f"🏦 {tt['mcap']}: {M.fmt_big(coin['market_cap'], currency)}")
    if coin.get("total_volume"):
        extra.append(f"🔁 {tt['vol']}: {M.fmt_big(coin['total_volume'], currency)}")
    if coin.get("ath"):
        ath_chg = coin.get("ath_change_percentage")
        extra.append(f"🏔 {tt['ath']}: {M.fmt_price(coin['ath'], currency)}"
                     + (f" ({ath_chg:+.1f}%)" if ath_chg is not None else ""))
    if extra:
        lines.append("\n".join(extra))
    mine = []
    if holding:
        mine.append(tt["hold"].format(amt=fmt_amount(holding), sym=html.escape(sym),
                                      val=M.fmt_money(holding * (coin.get("current_price") or 0), currency)))
    if alerts_n:
        mine.append(tt["alerts_on"].format(n=alerts_n))
    if mine:
        lines.append("\n".join(mine))
    return "\n\n".join(lines)


def card_markup(lang: str, coin: dict, fav: bool, share: bool):
    tt = TT[lang]
    cid = coin["id"]
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton(tt["btn_alert"], callback_data=f"pa:menu:{cid}"),
           types.InlineKeyboardButton(tt["btn_pf"], callback_data=f"pf:ask:{cid}"))
    kb.row(types.InlineKeyboardButton(tt["btn_fav_del" if fav else "btn_fav_add"], callback_data=f"c:fav:{cid}"),
           types.InlineKeyboardButton(tt["btn_game"], callback_data=f"c:g:{cid}"))
    last = [types.InlineKeyboardButton(tt["btn_refresh"], callback_data=f"c:r:{cid}")]
    if share:
        last.append(types.InlineKeyboardButton(tt["btn_share"], switch_inline_query=coin["symbol"].upper()))
    kb.row(*last)
    return kb


def card(chat_id: int, s: dict, coin_id: str, share: bool):
    """(текст, кнопки) карточки монеты для пользователя или None, если монеты нет в топ-200."""
    coin = _coin_in(s["currency"], coin_id)
    if coin is None:
        return None
    holding = next((a for cid, _, a in db.holdings(chat_id) if cid == coin_id), None)
    alerts_n = sum(1 for a in db.alerts_list(chat_id) if a[1] == coin_id)
    text = card_text(coin, s["lang"], s["currency"], holding, alerts_n)
    return text, card_markup(s["lang"], coin, coin_id in s["custom_coins"], share)


# ------------------------------------------------------------------
# Ценовые алерты
# ------------------------------------------------------------------
LEVELS = (5, 10, 20)


def alert_menu(s: dict, coin_id: str):
    tt, cur = TT[s["lang"]], s["currency"]
    coin = _coin_in(cur, coin_id)
    if coin is None or not coin.get("current_price"):
        return None
    price = coin["current_price"]
    kb = types.InlineKeyboardMarkup()
    kb.row(*[types.InlineKeyboardButton(f"📈 +{p}% · {M.fmt_price(price * (1 + p / 100), cur)}",
                                        callback_data=f"pa:add:{coin_id}:{p}") for p in LEVELS[:2]])
    kb.row(*[types.InlineKeyboardButton(f"📉 −{p}% · {M.fmt_price(price * (1 - p / 100), cur)}",
                                        callback_data=f"pa:add:{coin_id}:-{p}") for p in LEVELS[:2]])
    kb.row(types.InlineKeyboardButton(f"📈 +{LEVELS[2]}%", callback_data=f"pa:add:{coin_id}:{LEVELS[2]}"),
           types.InlineKeyboardButton(f"📉 −{LEVELS[2]}%", callback_data=f"pa:add:{coin_id}:-{LEVELS[2]}"))
    kb.row(types.InlineKeyboardButton(tt["btn_custom"], callback_data=f"pa:ask:{coin_id}"))
    text = tt["alert_pick"].format(sym=html.escape(coin["symbol"].upper()), price=M.fmt_price(price, cur))
    return text, kb


def ask_price_text(s: dict, coin_id: str):
    tt, cur = TT[s["lang"]], s["currency"]
    coin = _coin_in(cur, coin_id)
    if coin is None:
        return None, None
    ex = _example(coin.get("current_price"))
    text = tt["ask_price"].format(sym=html.escape(coin["symbol"].upper()), cur=cur.upper(),
                                  price=M.fmt_price(coin.get("current_price"), cur), ex=ex)
    return text, tt["placeholder_price"].format(ex=ex)


def add_alert(chat_id: int, s: dict, coin_id: str, target: float = None, pct: float = None) -> str:
    """Создаёт алерт по цене target или по проценту pct от текущей. Возвращает текст ответа."""
    tt, cur = TT[s["lang"]], s["currency"]
    coin = _coin_in(cur, coin_id)
    if coin is None or not coin.get("current_price"):
        return TT[s["lang"]]["not_found"].format(q=html.escape(coin_id))
    price = coin["current_price"]
    if target is None:
        target = price * (1 + pct / 100)
    if abs(target - price) / price < 0.0005:
        return tt["alert_same"]
    direction = 1 if target > price else -1
    sym = coin["symbol"].upper()
    res = db.alert_add(chat_id, coin_id, sym, cur, target, direction, ALERT_LIMIT)
    if res == "limit":
        return tt["alert_limit"].format(n=ALERT_LIMIT)
    if res == "dup":
        return tt["alert_dup"]
    return tt["alert_set"].format(sym=html.escape(sym), dir=tt["above" if direction > 0 else "below"],
                                  target=M.fmt_price(target, cur), price=M.fmt_price(price, cur))


def alerts_view(chat_id: int, s: dict):
    tt = TT[s["lang"]]
    rows = db.alerts_list(chat_id)
    if not rows:
        return tt["alerts_empty"], None
    lines, kb = [tt["alerts_title"], ""], types.InlineKeyboardMarkup()
    btns = []
    for i, (aid, coin_id, sym, cur, target, direction) in enumerate(rows, start=1):
        coin = _coin_in(cur, coin_id)
        now = M.fmt_price(coin.get("current_price"), cur) if coin else "—"
        arrow = "📈 ≥" if direction > 0 else "📉 ≤"
        lines.append(f"{M.keycap(i)} <b>{html.escape(sym)}</b> {arrow} {M.fmt_price(target, cur)}  ·  {now}")
        btns.append(types.InlineKeyboardButton(f"✖️ {i}. {sym}", callback_data=f"pa:del:{aid}"))
    for j in range(0, len(btns), 3):
        kb.row(*btns[j:j + 3])
    lines += ["", tt["alerts_hint"]]
    return "\n".join(lines), kb


def check_price_alerts() -> list:
    """Проверяет все активные алерты. Возвращает сообщения [(chat_id, text, lang, silent, markup)]."""
    out = []
    for cur in db.alerts_currencies():
        try:
            data = M.get_markets(cur)
        except Exception:
            continue
        prices = {c["id"]: c["current_price"] for c in data if c.get("current_price")}
        by_id = {c["id"]: c for c in data}
        for chat_id, coin_id, sym, target, direction, s in db.alerts_trigger(cur, prices):
            tt, coin = TT[s["lang"]], by_id.get(coin_id, {})
            head = tt["alert_hit_up" if direction > 0 else "alert_hit_down"].format(
                sym=html.escape(sym), target=M.fmt_price(target, cur))
            body = tt["alert_now"].format(price=M.fmt_price(coin.get("current_price"), cur),
                                          chg=M.fmt_pct(coin.get("price_change_percentage_24h_in_currency")))
            kb = types.InlineKeyboardMarkup()
            kb.row(types.InlineKeyboardButton(tt["btn_alert"], callback_data=f"pa:menu:{coin_id}"),
                   types.InlineKeyboardButton("📊 " + sym, callback_data=f"c:o:{coin_id}"))
            out.append((chat_id, f"{head}\n{body}", s["lang"], s, kb))
    return out


# ------------------------------------------------------------------
# Портфель
# ------------------------------------------------------------------
def _valuate(holdings: list, data: list):
    """[(coin, amount, value, change24_value)], итоговая стоимость, изменение за 24ч, за 7д."""
    by_id = {c["id"]: c for c in data}
    rows, total, d24, d7 = [], 0.0, 0.0, 0.0
    for coin_id, sym, amount in holdings:
        c = by_id.get(coin_id)
        if not c or not c.get("current_price"):
            continue
        value = amount * c["current_price"]
        p24 = c.get("price_change_percentage_24h_in_currency") or 0.0
        p7 = c.get("price_change_percentage_7d_in_currency") or 0.0
        ch24 = value - value / (1 + p24 / 100)
        d7 += value - value / (1 + p7 / 100)
        rows.append((c, amount, value, ch24, p24))
        total += value
        d24 += ch24
    return rows, total, d24, d7


def _delta(delta: float, total: float, currency: str) -> str:
    base = total - delta
    pct = delta / base * 100 if base else 0.0
    arrow = "📈" if delta >= 0 else "📉"
    sign = "+" if delta >= 0 else "-"
    return f"{arrow} {sign}{M.fmt_money(abs(delta), currency)} ({pct:+.2f}%)"


def portfolio_view(chat_id: int, s: dict):
    tt, cur = TT[s["lang"]], s["currency"]
    hold = db.holdings(chat_id)
    kb = types.InlineKeyboardMarkup()
    if not hold:
        kb.row(types.InlineKeyboardButton(tt["btn_pf_add"], callback_data="pf:add"))
        return tt["pf_empty"], kb
    rows, total, d24, _ = _valuate(hold, M.get_markets(cur))
    rows.sort(key=lambda r: -r[2])
    lines = [tt["pf_title"], "", tt["pf_total"].format(val=M.fmt_money(total, cur), chg=_delta(d24, total, cur)), ""]
    for i, (c, amount, value, ch24, p24) in enumerate(rows, start=1):
        share = value / total * 100 if total else 0
        lines.append(f"{M.keycap(i)} <b>{html.escape(c['symbol'].upper())}</b> {fmt_amount(amount)} — "
                     f"{M.fmt_money(value, cur)} · {share:.0f}% ({M.fmt_pct(p24)})")
    lines += ["", f"<i>{tt['pf_note'].format(cur=cur.upper())}</i>"]
    btns = [types.InlineKeyboardButton(tt["btn_pf_edit"].format(sym=c["symbol"].upper()),
                                       callback_data=f"pf:ask:{c['id']}") for c, *_ in rows[:12]]
    for j in range(0, len(btns), 3):
        kb.row(*btns[j:j + 3])
    kb.row(types.InlineKeyboardButton(tt["btn_pf_add"], callback_data="pf:add"),
           types.InlineKeyboardButton("🔄", callback_data="pf:view"))
    return "\n".join(lines), kb


def ask_amount_text(s: dict, coin_id: str):
    coin = _coin_in("usd", coin_id)
    if coin is None:
        return None
    return TT[s["lang"]]["pf_ask"].format(sym=html.escape(coin["symbol"].upper()))


def set_holding(chat_id: int, s: dict, coin_id: str, amount: float) -> str:
    tt, cur = TT[s["lang"]], s["currency"]
    coin = _coin_in(cur, coin_id)
    if coin is None:
        return tt["not_found"].format(q=html.escape(coin_id))
    sym = coin["symbol"].upper()
    res = db.set_holding(chat_id, coin_id, sym, amount, PF_LIMIT)
    if res == "removed":
        return tt["pf_removed"].format(sym=html.escape(sym))
    if res == "limit":
        return tt["pf_limit"].format(n=PF_LIMIT)
    return tt["pf_saved"].format(amt=fmt_amount(amount), sym=html.escape(sym),
                                 val=M.fmt_money(amount * (coin.get("current_price") or 0), cur))


def portfolio_line(s: dict, hold: list, weekly: bool = False):
    """Короткая строка портфеля для отчётов (или за неделю для итогов). None, если портфеля нет."""
    if not hold or not s.get("show_portfolio", True):
        return None
    try:
        _, total, d24, d7 = _valuate(hold, M.get_markets(s["currency"]))
    except Exception:
        return None
    if not total:
        return None
    tt, cur = TT[s["lang"]], s["currency"]
    if weekly:
        return tt["pf_week"].format(val=M.fmt_money(total, cur), chg=_delta(d7, total, cur))
    return tt["pf_short"].format(val=M.fmt_money(total, cur), chg=_delta(d24, total, cur))
