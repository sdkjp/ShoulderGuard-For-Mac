#!/usr/bin/env python3
"""
ShoulderGuard - 第三者検出によるMacセキュリティスクリプト
"""

import cv2
import time
import subprocess
import os
import yaml
import threading
from datetime import datetime
from pathlib import Path

# ============================
# 設定読み込み
# ============================
CONFIG_PATH = Path(__file__).parent / "config.yaml"

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

# ============================
# アクション関数
# ============================

def action_lock_screen():
    """画面をロックする"""
    subprocess.run([
        "osascript", "-e",
        'tell application "System Events" to keystroke "q" using {control down, command down}'
    ])

def action_screenshot(frame, save_dir):
    """検出時のフレームを保存する"""
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = str(Path(save_dir) / f"intruder_{timestamp}.jpg")
    cv2.imwrite(filepath, frame)
    print(f"[ShoulderGuard] 📸 スクリーンショット保存: {filepath}")
    return filepath

def action_notify(title, message):
    """macOS通知を送る"""
    subprocess.run([
        "osascript", "-e",
        f'display notification "{message}" with title "{title}" sound name "Basso"'
    ])

def action_open_url(url):
    """指定URLをデフォルトブラウザで開く（別タブへ移動）"""
    subprocess.run(["open", url])

def action_play_sound():
    """警告音を鳴らす"""
    subprocess.run(["afplay", "/System/Library/Sounds/Basso.aiff"])

# ============================
# メイン検出ループ
# ============================

def run():
    config = load_config()
    settings = config.get("settings", {})
    actions = config.get("actions", {})

    # 設定値
    camera_index      = settings.get("camera_index", 0)
    check_interval    = settings.get("check_interval_sec", 1.0)
    cooldown_sec      = settings.get("cooldown_sec", 10)
    min_face_size     = tuple(settings.get("min_face_size", [60, 60]))
    scale_factor      = settings.get("scale_factor", 1.1)
    min_neighbors     = settings.get("min_neighbors", 5)
    screenshot_dir    = settings.get("screenshot_dir", "~/ShoulderGuard/captures")
    redirect_url      = settings.get("redirect_url", "https://www.google.com")
    show_preview      = settings.get("show_preview", False)

    screenshot_dir = str(Path(screenshot_dir).expanduser())

    # Haar Cascade 読み込み
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face_cascade = cv2.CascadeClassifier(cascade_path)

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print("[ShoulderGuard] ❌ カメラを開けませんでした。カメラの権限を確認してください。")
        return

    print("[ShoulderGuard] 🛡️  監視を開始しました。Ctrl+C で終了。")
    action_notify("ShoulderGuard", "監視を開始しました 🛡️")

    last_triggered = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ShoulderGuard] ⚠️  フレームを取得できませんでした。")
                time.sleep(check_interval)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=scale_factor,
                minNeighbors=min_neighbors,
                minSize=min_face_size
            )

            face_count = len(faces)
            now = time.time()

            if show_preview:
                for (x, y, w, h) in faces:
                    cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                cv2.putText(frame, f"Faces: {face_count}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.imshow("ShoulderGuard Preview", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            # 2人以上検出 → 第三者あり
            if face_count >= 2 and (now - last_triggered) > cooldown_sec:
                last_triggered = now
                print(f"[ShoulderGuard] 🚨 第三者を検出！ ({face_count}人の顔を検出)")

                # --- スクリーンショット（先に撮る）---
                saved_path = None
                if actions.get("screenshot", True):
                    saved_path = action_screenshot(frame, screenshot_dir)

                # --- 通知 ---
                if actions.get("notify", True):
                    action_notify(
                        "⚠️ ShoulderGuard 警告",
                        f"{face_count}人の顔を検出しました！"
                    )

                # --- 警告音 ---
                if actions.get("play_sound", False):
                    threading.Thread(target=action_play_sound, daemon=True).start()

                # --- 別タブ/URLへ移動 ---
                if actions.get("open_url", False):
                    action_open_url(redirect_url)

                # --- 画面ロック（最後に実行）---
                if actions.get("lock_screen", True):
                    print("[ShoulderGuard] 🔒 画面をロックします...")
                    time.sleep(0.5)
                    action_lock_screen()

            time.sleep(check_interval)

    except KeyboardInterrupt:
        print("\n[ShoulderGuard] 監視を終了しました。")
    finally:
        cap.release()
        if show_preview:
            cv2.destroyAllWindows()

if __name__ == "__main__":
    run()
