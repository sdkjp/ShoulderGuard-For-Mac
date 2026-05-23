#!/usr/bin/env python3
"""
ShoulderGuard GUI — macOS ネイティブスタイルのセキュリティモニター

顔認識モード (face_recognition インストール済み):
  登録した顔が映っていて、かつ別の顔が映ったときにアクション実行

フォールバックモード:
  2 人以上の顔を検出したときにアクション実行
"""

import queue
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import json
import yaml
from PIL import Image

try:
    import customtkinter as ctk
except ImportError:
    raise SystemExit("pip install customtkinter Pillow pyyaml opencv-python")

# face_recognition (dlib) が使えるかチェック — 使えない場合は 2人検出モードで動作
try:
    import face_recognition as _fr
    import numpy as np
    FR_AVAILABLE = True
except ImportError:
    FR_AVAILABLE = False

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

CONFIG_PATH   = Path(__file__).parent / "config.yaml"
FACE_DIR      = Path(__file__).parent / "face_data"
ENCODING_PATH = FACE_DIR / "owner_encoding.npy"


# ── 設定 I/O ──────────────────────────────────────────────────────────────

def list_cameras() -> list[tuple[int, str]]:
    """AVFoundation のデバイス順（= OpenCV インデックス）でカメラ一覧を返す"""
    import re
    cameras: list[tuple[int, str]] = []
    try:
        result = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=5,
        )
        in_video = False
        for line in (result.stdout + result.stderr).splitlines():
            if "AVFoundation video devices" in line:
                in_video = True
                continue
            if "AVFoundation audio devices" in line:
                break
            if in_video:
                m = re.search(r'\[(\d+)\]\s+(.+)', line)
                if m:
                    idx  = int(m.group(1))
                    name = m.group(2).strip()
                    if "Capture screen" not in name:
                        cameras.append((idx, name))
    except Exception:
        pass

    if not cameras:
        for idx in range(4):
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                cap.release()
                cameras.append((idx, f"カメラ {idx}"))

    return cameras if cameras else [(0, "デフォルトカメラ")]


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


# ── macOS アクション ──────────────────────────────────────────────────────

def _lock_screen():
    subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to keystroke "q" using {control down, command down}'],
        capture_output=True,
    )


def _save_photo(frame, directory: str) -> str:
    Path(directory).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = str(Path(directory) / f"intruder_{ts}.jpg")
    cv2.imwrite(path, frame)
    return path


def _notify(title: str, message: str):
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{message}" with title "{title}" sound name "Basso"'],
        capture_output=True,
    )


def _open_url(url: str):
    subprocess.run(["open", url])


def _play_sound():
    subprocess.run(["afplay", "/System/Library/Sounds/Basso.aiff"])


# ── 顔認識ユーティリティ ──────────────────────────────────────────────────

def load_owner_encoding():
    """保存済みの顔エンコーディングを読み込む。なければ None を返す。"""
    if not FR_AVAILABLE or not ENCODING_PATH.exists():
        return None
    return np.load(str(ENCODING_PATH))  # shape: (N, 128)


def save_owner_encoding(encodings: list):
    """複数フレームのエンコーディングを保存する。推論時に多数決で照合。"""
    FACE_DIR.mkdir(parents=True, exist_ok=True)
    arr = np.array(encodings)         # (N, 128)
    np.save(str(ENCODING_PATH), arr)


def detect_intruder(frame, owner_encodings, cascade, scale, min_nb, min_face):
    """
    Returns (owner_count, unknown_count, face_rects)
    face_rects: list of (x, y, w, h, is_owner: bool)
    """
    face_rects = []

    if not FR_AVAILABLE or owner_encodings is None:
        # フォールバック：Haar のみ（所有者不明として全員カウント）
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        haar_faces = cascade.detectMultiScale(gray, scaleFactor=scale,
                                               minNeighbors=min_nb, minSize=min_face)
        for (x, y, w, h) in haar_faces:
            face_rects.append((x, y, w, h, False))
        return 0, len(haar_faces), face_rects

    # face_recognition による判定（全顔を検出して照合）
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    locs = _fr.face_locations(rgb, model="hog")
    encs = _fr.face_encodings(rgb, locs)

    owner_count   = 0
    unknown_count = 0

    for (top, right, bottom, left), enc in zip(locs, encs):
        # owner_encodings (N, 128) に対して多数決
        matches  = _fr.compare_faces(list(owner_encodings), enc, tolerance=0.52)
        is_owner = matches.count(True) > matches.count(False)
        face_rects.append((left, top, right - left, bottom - top, is_owner))
        if is_owner:
            owner_count += 1
        else:
            unknown_count += 1

    return owner_count, unknown_count, face_rects


# ── 顔登録ウィンドウ ──────────────────────────────────────────────────────

class RegisterFaceWindow(ctk.CTkToplevel):
    """カメラ映像を表示しながら顔エンコーディングを収集・保存するウィンドウ"""

    CAPTURE_FRAMES = 8
    COUNTDOWN_SEC  = 3

    def __init__(self, parent, on_success):
        super().__init__(parent)
        self.title("顔を登録")
        self.geometry("480x420")
        self.resizable(False, False)
        self._on_success = on_success
        cfg = load_config()
        self._camera_index = cfg.get("settings", {}).get("camera_index", 0)
        self._stop_evt   = threading.Event()
        self._frame_q: queue.Queue = queue.Queue(maxsize=2)
        self._state      = "preview"
        self._countdown  = self.COUNTDOWN_SEC
        self._captured   = []
        self._img_ref    = None

        self._build_ui()
        threading.Thread(target=self._capture_loop, daemon=True).start()
        self._poll()

    def _build_ui(self):
        self._img_lbl = ctk.CTkLabel(self, text="")
        self._img_lbl.pack(expand=True, fill="both", padx=12, pady=(12, 4))

        self._info_lbl = ctk.CTkLabel(
            self, text="顔をカメラの中央に合わせてください",
            font=ctk.CTkFont(size=13),
        )
        self._info_lbl.pack(pady=4)

        self._btn = ctk.CTkButton(
            self, text="撮影開始",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start_countdown,
        )
        self._btn.pack(pady=(4, 14))

    def _capture_loop(self):
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            self._state = "error"
            return

        while not self._stop_evt.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(80, 80))

            if not self._frame_q.full():
                self._frame_q.put_nowait((frame.copy(), list(faces)))

            if self._state == "capturing" and FR_AVAILABLE:
                rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                locs = _fr.face_locations(rgb, model="hog")
                encs = _fr.face_encodings(rgb, locs)
                if encs:
                    self._captured.append(encs[0])
                    if len(self._captured) >= self.CAPTURE_FRAMES:
                        self._state = "saving"

            time.sleep(0.08)

        cap.release()

    def _start_countdown(self):
        if self._state != "preview":
            return
        self._btn.configure(state="disabled")
        self._state    = "countdown"
        self._countdown = self.COUNTDOWN_SEC
        self._tick()

    def _tick(self):
        if self._countdown > 0:
            self._info_lbl.configure(text=f"{self._countdown}...")
            self._countdown -= 1
            self.after(1000, self._tick)
        else:
            self._info_lbl.configure(text="撮影中...")
            self._captured.clear()
            self._state = "capturing"

    def _poll(self):
        try:
            frame, faces = self._frame_q.get_nowait()
            color = (30, 200, 30) if faces else (100, 100, 220)
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(rgb).resize((456, 320), Image.LANCZOS)
            img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(456, 320))
            self._img_lbl.configure(image=img, text="")
            self._img_ref = img
        except queue.Empty:
            pass

        if self._state == "saving":
            self._state = "done"
            self._stop_evt.set()
            if self._captured:
                save_owner_encoding(self._captured)
                self._info_lbl.configure(
                    text=f"✓ 登録完了（{len(self._captured)} フレーム取得）",
                    text_color="#27ae60",
                )
                self._btn.configure(
                    text="閉じる", state="normal",
                    command=lambda: (self._on_success(), self.destroy()),
                )
            else:
                self._state = "error"

        if self._state == "error":
            self._info_lbl.configure(
                text="顔を検出できませんでした。やり直してください。",
                text_color="#e74c3c",
            )
            self._btn.configure(text="やり直す", state="normal",
                                  command=self._retry)

        if self._state not in ("done", "error"):
            self.after(80, self._poll)

    def _retry(self):
        self._state    = "preview"
        self._captured.clear()
        self._stop_evt.clear()
        self._info_lbl.configure(
            text="顔をカメラの中央に合わせてください",
            text_color=("gray10", "gray90"),
        )
        self._btn.configure(text="撮影開始", state="normal",
                              command=self._start_countdown)
        threading.Thread(target=self._capture_loop, daemon=True).start()
        self._poll()


# ── メインアプリ ──────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._cfg       = load_config()
        self._owner_enc = load_owner_encoding()   # None or np.ndarray (N, 128)

        self._monitoring    = False
        self._stop_evt      = threading.Event()
        self._owner_count   = 0
        self._unknown_count = 0
        self._cam_error     = False
        self._last_alert    = None
        self._last_photo    = None

        self._frame_q        = queue.Queue(maxsize=3)
        self._preview_win    = None
        self._preview_img_ref = None

        self._setup_window()
        self._build_ui()
        self._poll()

    # ── ウィンドウ ────────────────────────────────────────────────────────

    def _setup_window(self):
        self.title("ShoulderGuard")
        self.geometry("390x660")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI 構築 ───────────────────────────────────────────────────────────

    def _build_ui(self):
        s = self._cfg.get("settings", {})
        a = self._cfg.get("actions", {})

        # ヘッダー
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=22, pady=(20, 0))
        ctk.CTkLabel(
            hdr, text="🛡️  ShoulderGuard",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left")

        # 顔認識バッジ
        self._face_badge = ctk.CTkLabel(
            self, text=self._badge_text(),
            font=ctk.CTkFont(size=11),
            fg_color=self._badge_color(),
            corner_radius=8, padx=8, pady=2,
            text_color="white",
        )
        self._face_badge.pack(anchor="w", padx=22, pady=(6, 0))

        # ステータスカード
        card = ctk.CTkFrame(self, corner_radius=14)
        card.pack(fill="x", padx=22, pady=12)

        toggle_row = ctk.CTkFrame(card, fg_color="transparent")
        toggle_row.pack(fill="x", padx=18, pady=(16, 6))
        ctk.CTkLabel(
            toggle_row, text="監視",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")
        self._switch = ctk.CTkSwitch(
            toggle_row, text="", width=52, command=self._on_toggle,
        )
        self._switch.pack(side="right")

        self._status_lbl = ctk.CTkLabel(
            card, text="停止中",
            font=ctk.CTkFont(size=13), text_color=("gray50", "gray60"),
        )
        self._status_lbl.pack(pady=(0, 4))

        self._alert_lbl = ctk.CTkLabel(
            card, text="",
            font=ctk.CTkFont(size=11), text_color=("gray60", "gray50"),
        )
        self._alert_lbl.pack(pady=(0, 14))

        # 顔登録ボタン
        reg_row = ctk.CTkFrame(self, fg_color="transparent")
        reg_row.pack(fill="x", padx=22, pady=(0, 6))

        self._reg_btn = ctk.CTkButton(
            reg_row,
            text=self._reg_text(),
            fg_color=("gray82", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray72", "gray32"),
            font=ctk.CTkFont(size=13),
            state="normal" if FR_AVAILABLE else "disabled",
            command=self._open_registration,
        )
        self._reg_btn.pack(side="left", expand=True, fill="x", padx=(0, 7))

        self._del_btn = ctk.CTkButton(
            reg_row, text="🗑",
            fg_color=("gray82", "gray25"),
            text_color=("#c0392b", "#e74c3c"),
            hover_color=("gray72", "gray32"),
            font=ctk.CTkFont(size=13), width=44,
            command=self._delete_face,
        )
        if self._owner_enc is not None:
            self._del_btn.pack(side="right")

        # タブ
        tabs = ctk.CTkTabview(self, height=318)
        tabs.pack(fill="x", padx=22, pady=4)
        self._build_actions_tab(tabs.add("アクション"), a, s)
        self._build_timing_tab(tabs.add("タイミング"), s)

        # ボタン行
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=22, pady=(10, 20))

        ctk.CTkButton(
            btn_row, text="📷  プレビュー",
            fg_color=("gray82", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray72", "gray32"),
            command=self._open_preview,
        ).pack(side="left", expand=True, fill="x", padx=(0, 7))

        ctk.CTkButton(
            btn_row, text="🔒  今すぐロック",
            fg_color="#c0392b", hover_color="#a93226",
            command=_lock_screen,
        ).pack(side="right", expand=True, fill="x", padx=(7, 0))

    def _badge_text(self) -> str:
        if not FR_AVAILABLE:
            return "顔認識: 未インストール（2人検出モード）"
        if self._owner_enc is None:
            return "顔未登録（2人検出モードで動作）"
        return f"顔認識: 登録済み（{len(self._owner_enc)} サンプル）"

    def _badge_color(self):
        if not FR_AVAILABLE:
            return ("gray55", "gray40")
        if self._owner_enc is None:
            return ("#e67e22", "#d35400")
        return ("#27ae60", "#1e8449")

    def _reg_text(self) -> str:
        if not FR_AVAILABLE:
            return "顔認識ライブラリ未インストール"
        if self._owner_enc is None:
            return "👤  自分の顔を登録する"
        return "👤  顔を再登録する"

    def _refresh_face_ui(self):
        self._face_badge.configure(text=self._badge_text(), fg_color=self._badge_color())
        self._reg_btn.configure(text=self._reg_text())
        if self._owner_enc is not None:
            self._del_btn.pack(side="right")
        else:
            self._del_btn.pack_forget()

    # ── アクションタブ ────────────────────────────────────────────────────

    def _build_actions_tab(self, parent, a: dict, s: dict):
        ITEMS = [
            ("lock_screen", "画面ロック",     True),
            ("screenshot",  "写真を保存",     True),
            ("notify",      "通知を表示",     True),
            ("play_sound",  "警告音を鳴らす",  False),
            ("open_url",    "URLを開く",      False),
        ]
        self._chk: dict[str, ctk.CTkCheckBox] = {}
        for key, label, default in ITEMS:
            chk = ctk.CTkCheckBox(parent, text=label,
                                   font=ctk.CTkFont(size=13),
                                   command=self._save_actions)
            if a.get(key, default):
                chk.select()
            chk.pack(anchor="w", padx=14, pady=3)
            self._chk[key] = chk

        url_frame = ctk.CTkFrame(parent, fg_color="transparent")
        url_frame.pack(fill="x", padx=14, pady=(2, 6))
        ctk.CTkLabel(url_frame, text="リダイレクト先:",
                      font=ctk.CTkFont(size=11),
                      text_color=("gray55", "gray55")).pack(anchor="w")
        self._url_entry = ctk.CTkEntry(url_frame, font=ctk.CTkFont(size=12),
                                        placeholder_text="https://www.google.com")
        self._url_entry.insert(0, s.get("redirect_url", "https://www.google.com"))
        self._url_entry.pack(fill="x", pady=(2, 0))
        self._url_entry.bind("<FocusOut>", lambda _: self._save_actions())
        self._chk["open_url"].configure(command=self._on_url_toggle)
        self._refresh_url_entry()

    def _on_url_toggle(self):
        self._refresh_url_entry()
        self._save_actions()

    def _refresh_url_entry(self):
        self._url_entry.configure(
            state="normal" if self._chk["open_url"].get() else "disabled"
        )

    def _save_actions(self):
        a = self._cfg.setdefault("actions", {})
        for key, chk in self._chk.items():
            a[key] = bool(chk.get())
        self._cfg.setdefault("settings", {})["redirect_url"] = (
            self._url_entry.get() or "https://www.google.com"
        )
        save_config(self._cfg)

    # ── タイミングタブ ────────────────────────────────────────────────────

    def _build_timing_tab(self, parent, s: dict):
        ITEMS = [
            ("trigger_delay_sec",  "検出遅延",    s.get("trigger_delay_sec", 2.0),  0.5, 10.0, 19),
            ("cooldown_sec",       "クールダウン",  s.get("cooldown_sec", 15),         5,   120,  23),
            ("check_interval_sec", "チェック間隔",  s.get("check_interval_sec", 1.0), 0.25, 3.0, 11),
        ]
        self._sliders: dict[str, ctk.CTkSlider] = {}
        for key, label, default, lo, hi, steps in ITEMS:
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=(10, 0))
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=13)).pack(side="left")
            val_lbl = ctk.CTkLabel(row, text=f"{default:.1f}秒",
                                    font=ctk.CTkFont(size=12), width=58, anchor="e")
            val_lbl.pack(side="right")
            slider = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=steps)
            slider.set(default)
            slider.pack(fill="x", padx=14, pady=(2, 0))

            def _on_slide(v, lbl=val_lbl):
                lbl.configure(text=f"{v:.1f}秒")
                self._save_timing()

            slider.configure(command=_on_slide)
            self._sliders[key] = slider

        # カメラ選択
        cam_row = ctk.CTkFrame(parent, fg_color="transparent")
        cam_row.pack(fill="x", padx=14, pady=(14, 0))
        ctk.CTkLabel(cam_row, text="カメラ", font=ctk.CTkFont(size=13)).pack(side="left")

        self._cameras = list_cameras()
        cam_names = [name for _, name in self._cameras]
        current_idx = s.get("camera_index", 0)
        current_cam_name = next(
            (name for i, name in self._cameras if i == current_idx),
            cam_names[0] if cam_names else "カメラ 0",
        )
        self._cam_menu = ctk.CTkOptionMenu(
            parent, values=cam_names,
            font=ctk.CTkFont(size=12),
            command=self._on_camera_change,
        )
        self._cam_menu.set(current_cam_name)
        self._cam_menu.pack(fill="x", padx=14, pady=(4, 6))

    def _on_camera_change(self, name: str):
        idx = next((i for i, n in self._cameras if n == name), 0)
        self._cfg.setdefault("settings", {})["camera_index"] = idx
        save_config(self._cfg)
        if self._monitoring:
            self._stop_monitoring()
            self._switch.deselect()
            self._status_lbl.configure(
                text="カメラ変更: 監視を再開してください",
                text_color="#e67e22",
            )

    def _save_timing(self):
        s = self._cfg.setdefault("settings", {})
        s["trigger_delay_sec"]  = round(self._sliders["trigger_delay_sec"].get(), 2)
        s["cooldown_sec"]       = round(self._sliders["cooldown_sec"].get(), 2)
        s["check_interval_sec"] = round(self._sliders["check_interval_sec"].get(), 2)
        save_config(self._cfg)

    # ── 顔登録 ────────────────────────────────────────────────────────────

    def _open_registration(self):
        if not FR_AVAILABLE:
            return
        RegisterFaceWindow(self, on_success=self._on_face_registered)

    def _on_face_registered(self):
        self._owner_enc = load_owner_encoding()
        self._refresh_face_ui()

    def _delete_face(self):
        if ENCODING_PATH.exists():
            ENCODING_PATH.unlink()
        self._owner_enc = None
        self._refresh_face_ui()

    # ── 監視トグル ────────────────────────────────────────────────────────

    def _on_toggle(self):
        if self._switch.get():
            self._start_monitoring()
        else:
            self._stop_monitoring()

    def _start_monitoring(self):
        self._owner_count   = 0
        self._unknown_count = 0
        self._cam_error     = False
        self._stop_evt.clear()
        self._monitoring = True
        threading.Thread(target=self._monitor_loop, daemon=True).start()

    def _stop_monitoring(self):
        self._stop_evt.set()
        self._monitoring = False

    def _monitor_loop(self):
        cfg = load_config()
        st  = cfg.get("settings", {})

        interval   = st.get("check_interval_sec", 1.0)
        cooldown   = st.get("cooldown_sec", 15)
        trig_delay = st.get("trigger_delay_sec", 2.0)
        min_face   = tuple(st.get("min_face_size", [60, 60]))
        scale      = st.get("scale_factor", 1.1)
        min_nb     = st.get("min_neighbors", 5)
        photo_dir  = str(Path(st.get("screenshot_dir",
                                      "~/ShoulderGuard/captures")).expanduser())

        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        cap = cv2.VideoCapture(st.get("camera_index", 0))
        if not cap.isOpened():
            self._cam_error = True
            return

        multi_since = None
        last_trig   = 0.0

        while not self._stop_evt.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(interval)
                continue

            oc, uc, rects = detect_intruder(
                frame, self._owner_enc, cascade, scale, min_nb, min_face
            )
            self._owner_count   = oc
            self._unknown_count = uc

            if not self._frame_q.full():
                self._frame_q.put_nowait((frame.copy(), rects))

            # トリガー判定
            if self._owner_enc is not None and FR_AVAILABLE:
                should_alert = oc >= 1 and uc >= 1   # 自分がいて+別人がいる
            else:
                should_alert = (oc + uc) >= 2         # フォールバック: 2人以上

            now = time.time()
            if should_alert:
                if multi_since is None:
                    multi_since = now
                elif now - multi_since >= trig_delay and now - last_trig >= cooldown:
                    last_trig   = now
                    multi_since = None
                    self._last_alert = datetime.now()
                    self._do_actions(cfg, frame, photo_dir)
            else:
                multi_since = None

            time.sleep(interval)

        cap.release()

    def _do_actions(self, cfg: dict, frame, photo_dir: str):
        a  = cfg.get("actions", {})
        st = cfg.get("settings", {})
        if a.get("screenshot", True):
            self._last_photo = _save_photo(frame, photo_dir)
        if a.get("notify", True):
            _notify("ShoulderGuard 警告", "第三者を検出しました")
        if a.get("play_sound", False):
            threading.Thread(target=_play_sound, daemon=True).start()
        if a.get("open_url", False):
            _open_url(st.get("redirect_url", "https://www.google.com"))
        if a.get("lock_screen", True):
            time.sleep(0.6)
            _lock_screen()

    # ── UI 定期更新 ──────────────────────────────────────────────────────

    def _poll(self):
        if self._cam_error:
            self._status_lbl.configure(
                text="カメラエラー（システム設定で権限を確認）",
                text_color="#e74c3c",
            )
        elif self._monitoring:
            oc, uc = self._owner_count, self._unknown_count
            if FR_AVAILABLE and self._owner_enc is not None:
                if oc == 0 and uc == 0:
                    txt, col = "👁  顔を検出していません", ("gray50", "gray60")
                elif oc >= 1 and uc == 0:
                    txt, col = "👤  正常（あなたのみ）", "#27ae60"
                elif oc == 0 and uc >= 1:
                    txt, col = f"👁  不明な人物を検出（{uc}人）", "#e67e22"
                else:
                    txt, col = f"⚠️  第三者を検出！（不明: {uc}人）", "#e74c3c"
            else:
                total = oc + uc
                if total == 0:
                    txt, col = "👁  顔を検出していません", ("gray50", "gray60")
                elif total == 1:
                    txt, col = "👤  正常（1人）", "#27ae60"
                else:
                    txt, col = f"⚠️  第三者を検出！（{total}人）", "#e74c3c"
            self._status_lbl.configure(text=txt, text_color=col)
        else:
            self._status_lbl.configure(text="停止中", text_color=("gray50", "gray60"))

        if self._last_alert:
            ts   = self._last_alert.strftime("%H:%M:%S")
            note = f"  📸 {Path(self._last_photo).name}" if self._last_photo else ""
            self._alert_lbl.configure(text=f"最終アラート: {ts}{note}")

        if self._preview_win and self._preview_win.winfo_exists():
            self._refresh_preview_frame()

        self.after(500, self._poll)

    # ── プレビューウィンドウ ──────────────────────────────────────────────

    def _open_preview(self):
        if self._preview_win and self._preview_win.winfo_exists():
            self._preview_win.lift()
            return
        pw = ctk.CTkToplevel(self)
        pw.title("カメラプレビュー")
        pw.geometry("500x410")
        pw.resizable(False, False)
        self._preview_win = pw

        self._preview_img_lbl = ctk.CTkLabel(pw, text="")
        self._preview_img_lbl.pack(expand=True, fill="both", padx=12, pady=(12, 4))

        self._preview_info = ctk.CTkLabel(
            pw, text="起動中...",
            font=ctk.CTkFont(size=12), text_color=("gray55", "gray55"),
        )
        self._preview_info.pack(pady=(0, 10))

        if not self._monitoring:
            threading.Thread(target=self._preview_only_loop, daemon=True).start()

    def _preview_only_loop(self):
        cfg    = load_config()
        st     = cfg.get("settings", {})
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        cap = cv2.VideoCapture(st.get("camera_index", 0))
        if not cap.isOpened():
            return

        scale  = st.get("scale_factor", 1.1)
        min_nb = st.get("min_neighbors", 5)
        min_fs = tuple(st.get("min_face_size", [60, 60]))

        while (self._preview_win and self._preview_win.winfo_exists()
               and not self._monitoring):
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue
            _, _, rects = detect_intruder(frame, self._owner_enc, cascade,
                                           scale, min_nb, min_fs)
            if not self._frame_q.full():
                self._frame_q.put_nowait((frame.copy(), rects))
            time.sleep(0.08)

        cap.release()

    def _refresh_preview_frame(self):
        try:
            frame, rects = self._frame_q.get_nowait()
        except queue.Empty:
            return

        for x, y, w, h, is_owner in rects:
            color = (30, 200, 30) if is_owner else (30, 30, 220)
            label = "あなた" if is_owner else "不明"
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, label, (x, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)

        rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil    = Image.fromarray(rgb).resize((476, 350), Image.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(476, 350))
        self._preview_img_lbl.configure(image=ctk_img, text="")
        self._preview_img_ref = ctk_img

        owners   = sum(1 for *_, o in rects if o)
        unknowns = sum(1 for *_, o in rects if not o)
        if FR_AVAILABLE and self._owner_enc is not None:
            if unknowns:
                info, col = f"⚠️  あなた: {owners}人  不明: {unknowns}人", "#e67e22"
            else:
                info, col = (f"👤 あなた: {owners}人" if owners else "顔を検出中..."), ("gray55", "gray55")
        else:
            total = owners + unknowns
            info  = f"👤 {total}人" if total else "顔を検出中..."
            col   = "#e67e22" if total >= 2 else ("gray55", "gray55")
        self._preview_info.configure(text=info, text_color=col)

    # ── 終了 ──────────────────────────────────────────────────────────────

    def _on_close(self):
        self._stop_monitoring()
        self.quit()


# ── エントリーポイント ────────────────────────────────────────────────────

if __name__ == "__main__":
    App().mainloop()
