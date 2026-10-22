    try:
        currencies, ana_langs, fact_langs = db.active_currencies_langs()
        for cur in sorted(set(currencies) | {"usd"}):
            try:
                data = M.get_markets(cur, max_age=0)
                if cur == "usd":  # список топ-200 для выбора «своих монет» в мини-приложении
                    db.set_meta("top_coins", json.dumps(M.top_coins_snapshot(data), ensure_ascii=False))
            except Exception as e:
                logger.error("Prepare: market data unavailable (%s): %s", cur, e)
            time.sleep(2)
        M.get_indices(max_age=0)
        # к Gemini обращаемся редко: аналитика обновляется, только когда кэш старше AI_CACHE_MIN
        # (≈4 раза в сутки), факты пополняются пачкой ~2 раза в сутки; один запрос — все языки
        if ana_langs:
            M.get_ai_text("analysis", ana_langs[0])
        if fact_langs:
            refill_facts()
    except Exception:
        logger.exception("Prepare step failed")


def prepare_loop() -> None:
    """Прогрев при старте, затем в :28 и :58 каждого часа: обновляет курсы; аналитика и пул
    фактов обновляются только по необходимости (см. prepare). Пользователям всё отдаётся из кэша."""
    prepare()
    while not stop.is_set():
        t = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
        while t.minute not in (28, 58):
            t += timedelta(minutes=1)
        if not _sleep_until(t):
            return
        prepare()


def check_moves() -> None:
