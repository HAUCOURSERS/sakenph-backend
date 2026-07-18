#!/bin/bash

sudo dnf install -y python3-pip
sudo pip install uvicorn

cd /home/ec2-user/sakenph-backend
python3 -m venv venv
source venv/bin/activate
pip install -r /home/ec2-user/sakenph-backend/requirements.txt


