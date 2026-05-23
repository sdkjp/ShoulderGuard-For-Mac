#!/bin/bash
# ShoulderGuard GUI 起動スクリプト
cd "$(dirname "$0")"

# venv がなければ作成してインストール
if [ ! -d ".venv" ]; then
  echo "初回セットアップ中..."
  python3 -m venv .venv
  .venv/bin/pip install customtkinter Pillow pyyaml opencv-python -q
fi

.venv/bin/python3 shoulder_guard_gui.py
