#!/usr/bin/env bash
# Обновление бота на плате: ./update.sh
# Перед перезапуском прогоняет проверки: сломанный код не попадёт в работающий бот.
set -euo pipefail
cd "$(dirname "$0")"

git pull --ff-only
venv/bin/pip install -q -r requirements-dev.txt
venv/bin/python -m pyflakes ./*.py
venv/bin/python -m pytest -q tests
sudo systemctl restart cryptobot cryptobot-web
sleep 3
systemctl --no-pager --lines=0 status cryptobot cryptobot-web | grep -E "●|Active:"
