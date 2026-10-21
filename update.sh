#!/usr/bin/env bash
# Обновление бота на плате: ./update.sh
set -euo pipefail
cd "$(dirname "$0")"

git pull --ff-only
venv/bin/pip install -q -r requirements.txt
sudo systemctl restart cryptobot cryptobot-web
sleep 2
systemctl --no-pager --lines=0 status cryptobot cryptobot-web | grep -E "●|Active:"
