#!/bin/bash

APP_DIR="/home/ec2-user/sakenph-backend"
sed -i "s|WorkingDirectory=.*|WorkingDirectory=$APP_DIR|" /etc/systemd/system/uvicorn.service

systemctl daemon-reload

cd "$APP_DIR"
./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -r requirements.txt