#!/bin/bash

APP_DIR="/home/ec2-user/sakenph-backend"
sed -i "s|WorkingDirectory=.*|WorkingDirectory=$APP_DIR|" /etc/systemd/system/uvicorn.service

systemctl daemon-reload

cd "$APP_DIR"
pip install --upgrade pip
pip install -r requirements.txt