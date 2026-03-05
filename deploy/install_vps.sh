#!/usr/bin/env bash
set -euo pipefail
APP_DIR="/opt/krakenbot"
USER="krakenbot"

if ! id -u "$USER" >/dev/null 2>&1; then
  sudo useradd -m -s /bin/bash "$USER"
fi

sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER":"$USER" "$APP_DIR"

echo "Copying project into $APP_DIR (run from extracted project root)"
rsync -a --delete ./ "$APP_DIR/" --exclude venv --exclude .git --exclude __pycache__

sudo -u "$USER" bash -lc "cd $APP_DIR && python3 -m venv venv && source venv/bin/activate && pip install -U pip && pip install -r requirements.txt"

sudo cp "$APP_DIR/deploy/systemd/krakenbot.service" /etc/systemd/system/krakenbot.service
sudo systemctl daemon-reload
sudo systemctl enable krakenbot.service

echo "Done. Edit $APP_DIR/.env then:"
echo "  sudo systemctl start krakenbot"
echo "  journalctl -u krakenbot -f"
