#!/bin/bash
set -e

APP_DIR="/home/ec2-user/sakenph-backend"

sed -i "s|WorkingDirectory=.*|WorkingDirectory=$APP_DIR|" /etc/systemd/system/uvicorn.service

systemctl daemon-reload

"$APP_DIR/venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"