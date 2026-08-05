#!/bin/bash
set -e

sudo dnf install -y python3.11 python3.11-pip

APP_DIR="/home/ec2-user/sakenph-backend"

cd "$APP_DIR"

rm -rf venv
/usr/bin/python3.11 -m venv venv