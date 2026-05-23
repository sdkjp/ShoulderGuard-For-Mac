#!/usr/bin/env python3
"""
ShoulderGuard - 第三者検出によるMacセキュリティスクリプト

使い方:
  python shoulder_guard.py           # 監視開始
  python shoulder_guard.py preview   # カメラプレビュー（動作確認）
  python shoulder_guard.py config    # 設定を対話的に変更
"""

import argparse
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import yaml

CONFIG_PATH = Path(__file__).parent / "config.yaml"


# ============================================================
# 設定
# ============================================================

def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    print(f"設定を保存しました: {CONFIG_PATH}")


# ============================================================
# アクション
# ============================================================

def action_lock_screen():
    subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to keystroke "q" using {control down, command down}'],
        capture_output=True
    )


def action_screenshot(frame, save_dir: str) -> str:
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = str(Path(save_dir) / f"intruder_{timestamp}.jpg")
    cv2.imwrite(filepath, frame)
    print(f"[ShoulderGuard] 写真保存: {filepath}")
    return filepath


def action_notify(title: str, message: str):
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{message}" with title "{title}" sound name "Basso"'],
        capture_output=True
    )


def action_open_url(url: str):
    subprocess.run(["open", url])


def action_play_sound():
    subprocess.run(["afplay", "/System/Library/Sounds/Basso.aiff"])


def execute_actions(config: dict, frame):
    actions = config.get("actions", {})
    settings = config.get("settings", {})

    if actions.get("screenshot", True):
        action_screenshot(frame, str(Path(settings.get("screenshot_dir", "~/ShoulderGuard/captures")).expanduser()))

    if actions.get("notify", True):
        action_notify("ShoulderGuard 警告", "第三者を検出しました")

    if actions.get("play_sound", False):
        threading.Thread(target=action_play_sound, daemon=True).start()

    if actions.get("open_url", False):
        action_open_url(settings.get("redirect_url", "https://www.google.com"))

    if actions.get("lock_screen", True):
        print("[ShoulderGuard] 画面をロックします...")
        time.sleep(0.6)  # 写真・通知の処理を先に完了させる
        action_lock_screen()


# ============================================================
# 検出ループ
# ============================================================

def run(config: dict):
    settings = config.get("settings", {})

    camera_index      = settings.get("camera_index", 0)
    check_interval    = settings.get("check_interval_sec", 1.0)
    cooldown_sec      = settings.get("cooldown_sec", 15)
    trigger_delay_sec = settings.get("trigger_delay_sec", 2.0)
    min_face_size     = tuple(settings.get("min_face_size", [60, 60]))
    scale_factor      = settings.get("scale_factor", 1.1)
    min_neighbors     = settings.get("min_neighbors", 5)

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        print("[ShoulderGuard] カメラを開けませんでした。")
        print("システム設定 > プライバシーとセキュリティ > カメラ でターミナルを許可してください。")
        return

    print("[ShoulderGuard] 監視を開始しました。Ctrl+C で終了。")
    print(f"  検出遅延: {trigger_delay_sec}秒 / クールダウン: {cooldown_sec}秒")
    action_notify("ShoulderGuard", "監視を開始しました")

    last_triggered = 0.0
    multi_face_since = None  # 2人以上を最初に検出した時刻

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(check_interval)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(
                gray,
                scaleFactor=scale_factor,
                minNeighbors=min_neighbors,
                minSize=min_face_size
            )
            face_count = len(faces)
            now = time.time()

            if face_count >= 2:
                if multi_face_since is None:
                    multi_face_since = now
                    remaining = trigger_delay_sec
                    print(f"[ShoulderGuard] {face_count}人を検出。{remaining:.0f}秒継続でアクション実行...", flush=True)

                elif now - multi_face_since >= trigger_delay_sec:
                    if now - last_triggered >= cooldown_sec:
                        print(f"[ShoulderGuard] 第三者を確認！({face_count}人) アクション実行", flush=True)
                        execute_actions(config, frame)
                        last_triggered = now
                    multi_face_since = None
            else:
                if multi_face_since is not None:
                    print("[ShoulderGuard] 第三者が離れました", flush=True)
                multi_face_since = None

            time.sleep(check_interval)

    except KeyboardInterrupt:
        print("\n[ShoulderGuard] 監視を終了しました。")
    finally:
        cap.release()


# ============================================================
# プレビューモード
# ============================================================

def preview(config: dict):
    """カメラ映像をリアルタイム表示。顔検出の感度確認に使う。"""
    settings = config.get("settings", {})
    camera_index  = settings.get("camera_index", 0)
    scale_factor  = settings.get("scale_factor", 1.1)
    min_neighbors = settings.get("min_neighbors", 5)
    min_face_size = tuple(settings.get("min_face_size", [60, 60]))

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        print("[ShoulderGuard] カメラを開けませんでした。")
        return

    print("プレビューモード起動 (終了: q キー)")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=scale_factor,
                                         minNeighbors=min_neighbors, minSize=min_face_size)

        alert = len(faces) >= 2
        color = (0, 0, 255) if alert else (0, 200, 0)

        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

        label = f"検出: {len(faces)}人  {'[警告] 第三者あり' if alert else ''}"
        cv2.putText(frame, label, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
        cv2.imshow("ShoulderGuard Preview  (q: 終了)", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


# ============================================================
# 対話的設定変更
# ============================================================

def configure():
    config = load_config()

    ACTION_LABELS = {
        "notify":      "macOS通知を送る",
        "screenshot":  "写真を保存する",
        "play_sound":  "警告音を鳴らす",
        "open_url":    "指定URLをブラウザで開く",
        "lock_screen": "画面をロックする（最後に実行）",
    }

    while True:
        actions  = config.get("actions", {})
        settings = config.get("settings", {})

        print("\n=== ShoulderGuard 設定 ===")
        print("--- アクション ---")
        for i, (key, label) in enumerate(ACTION_LABELS.items(), start=1):
            state = "ON " if actions.get(key, False) else "OFF"
            print(f"  [{i}] [{state}] {label}")

        print("--- タイミング ---")
        print(f"  [6] 検出遅延:         {settings.get('trigger_delay_sec', 2.0)}秒  "
              f"（この秒数連続して2人以上検出でトリガー）")
        print(f"  [7] クールダウン:     {settings.get('cooldown_sec', 15)}秒  "
              f"（トリガー後の待機時間）")
        print(f"  [8] チェック間隔:     {settings.get('check_interval_sec', 1.0)}秒")
        print("--- その他 ---")
        print(f"  [9] リダイレクトURL:  {settings.get('redirect_url', 'https://www.google.com')}")
        print(f"  [10] 写真保存先:      {settings.get('screenshot_dir', '~/ShoulderGuard/captures')}")
        print("  [0] 終了")

        choice = input("\n変更する番号: ").strip()

        action_keys = list(ACTION_LABELS.keys())
        if choice in [str(i) for i in range(1, 6)]:
            key = action_keys[int(choice) - 1]
            config["actions"][key] = not actions.get(key, False)
            save_config(config)
            state = "ON" if config["actions"][key] else "OFF"
            print(f"  → {key} を {state} にしました")

        elif choice == "6":
            try:
                val = float(input(f"検出遅延（秒）[現在: {settings.get('trigger_delay_sec', 2.0)}]: ") or settings.get("trigger_delay_sec", 2.0))
                config["settings"]["trigger_delay_sec"] = val
                save_config(config)
            except ValueError:
                print("無効な値です")

        elif choice == "7":
            try:
                val = float(input(f"クールダウン（秒）[現在: {settings.get('cooldown_sec', 15)}]: ") or settings.get("cooldown_sec", 15))
                config["settings"]["cooldown_sec"] = val
                save_config(config)
            except ValueError:
                print("無効な値です")

        elif choice == "8":
            try:
                val = float(input(f"チェック間隔（秒）[現在: {settings.get('check_interval_sec', 1.0)}]: ") or settings.get("check_interval_sec", 1.0))
                config["settings"]["check_interval_sec"] = val
                save_config(config)
            except ValueError:
                print("無効な値です")

        elif choice == "9":
            val = input(f"リダイレクトURL [現在: {settings.get('redirect_url', '')}]: ").strip()
            if val:
                config["settings"]["redirect_url"] = val
                save_config(config)

        elif choice == "10":
            val = input(f"写真保存先 [現在: {settings.get('screenshot_dir', '')}]: ").strip()
            if val:
                config["settings"]["screenshot_dir"] = val
                save_config(config)

        elif choice == "0":
            break


# ============================================================
# エントリーポイント
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="ShoulderGuard - 第三者を検出してMacを自動制御",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
コマンド:
  (なし)    監視を開始する
  preview   カメラプレビューで顔検出を確認
  config    設定を対話的に変更する
""",
    )
    parser.add_argument(
        "command", nargs="?", default="start",
        choices=["start", "preview", "config"],
    )
    args = parser.parse_args()
    config = load_config()

    if args.command == "preview":
        preview(config)
    elif args.command == "config":
        configure()
    else:
        run(config)


if __name__ == "__main__":
    main()
