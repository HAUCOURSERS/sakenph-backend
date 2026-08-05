#!/bin/bash

sudo dnf install -y python3.11 python3.11-pip
sudo pip install uvicorn

cd /home/ec2-user/sakenph-backend

python3.11 -m venv venv
source venv/bin/activate