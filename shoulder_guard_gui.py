#!/usr/bin/env python3
"""ShoulderGuard GUI — macOS ネイティブスタイルのセキュリティモニター
起動: python shoulder_guard_gui.py
"""

import queue
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import yaml
from PIL import Image

try:
    import customtkinter as ctk
except ImportError:
    raise SystemExit("customtkinter が必要です: pip install customtkinter Pillow pyyaml opencv-python")

# macOS システムの外観（ダーク/ライト）に追従
ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

CONFIG_PATH = Path(__file__).parent / "config.yaml"


# ── 設定 I/O ──────────────────────────────────────────────────────────────

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


# ── GUI アプリ ────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._cfg = load_config()

        # 状態変数（監視スレッドと共有）
        self._monitoring = False
        self._stop_evt = threading.Event()
        self._face_count = 0
        self._cam_error = False
        self._last_alert = None   # datetime or None
        self._last_photo = None   # str or None

        # プレビュー用フレームキュー
        self._frame_q = queue.Queue(maxsize=3)
        self._preview_win = None
        self._preview_img_ref = None  # GC 防止

        self._setup_window()
        self._build_ui()
        self._poll()  # 定期 UI 更新スタート

    # ── ウィンドウ設定 ────────────────────────────────────────────────────

    def _setup_window(self):
        self.title("ShoulderGuard")
        self.geometry("390x560")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI 構築 ───────────────────────────────────────────────────────────

    def _build_ui(self):
        s = self._cfg.get("settings", {})
        a = self._cfg.get("actions", {})

        # ── ヘッダー ──────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=22, pady=(20, 0))
        ctk.CTkLabel(
            hdr, text="🛡️  ShoulderGuard",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left")

        # ── ステータスカード ──────────────────────────────────────────────
        card = ctk.CTkFrame(self, corner_radius=14)
        card.pack(fill="x", padx=22, pady=14)

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
            font=ctk.CTkFont(size=13),
            text_color=("gray50", "gray60"),
        )
        self._status_lbl.pack(pady=(0, 4))

        self._alert_lbl = ctk.CTkLabel(
            card, text="",
            font=ctk.CTkFont(size=11),
            text_color=("gray60", "gray50"),
        )
        self._alert_lbl.pack(pady=(0, 14))

        # ── タブビュー ────────────────────────────────────────────────────
        tabs = ctk.CTkTabview(self, height=278)
        tabs.pack(fill="x", padx=22, pady=4)
        self._build_actions_tab(tabs.add("アクション"), a, s)
        self._build_timing_tab(tabs.add("タイミング"), s)

        # ── ボタン行 ──────────────────────────────────────────────────────
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

    # ── アクションタブ ────────────────────────────────────────────────────

    def _build_actions_tab(self, parent, a: dict, s: dict):
        ITEMS = [
            ("lock_screen", "画面ロック",    True),
            ("screenshot",  "写真を保存",    True),
            ("notify",      "通知を表示",    True),
            ("play_sound",  "警告音を鳴らす", False),
            ("open_url",    "URLを開く",     False),
        ]
        self._chk: dict[str, ctk.CTkCheckBox] = {}

        for key, label, default in ITEMS:
            chk = ctk.CTkCheckBox(
                parent, text=label,
                font=ctk.CTkFont(size=13),
                command=self._save_actions,
            )
            if a.get(key, default):
                chk.select()
            chk.pack(anchor="w", padx=14, pady=3)
            self._chk[key] = chk

        # URL エントリ（「URLを開く」の状態に連動）
        url_frame = ctk.CTkFrame(parent, fg_color="transparent")
        url_frame.pack(fill="x", padx=14, pady=(2, 6))
        ctk.CTkLabel(
            url_frame, text="リダイレクト先:",
            font=ctk.CTkFont(size=11),
            text_color=("gray55", "gray55"),
        ).pack(anchor="w")
        self._url_entry = ctk.CTkEntry(
            url_frame, font=ctk.CTkFont(size=12),
            placeholder_text="https://www.google.com",
        )
        self._url_entry.insert(0, s.get("redirect_url", "https://www.google.com"))
        self._url_entry.pack(fill="x", pady=(2, 0))
        self._url_entry.bind("<FocusOut>", lambda _: self._save_actions())

        # 「URLを開く」チェックに連動してエントリを有効/無効化
        self._chk["open_url"].configure(command=self._on_url_toggle)
        self._refresh_url_entry()

    def _on_url_toggle(self):
        self._refresh_url_entry()
        self._save_actions()

    def _refresh_url_entry(self):
        state = "normal" if self._chk["open_url"].get() else "disabled"
        self._url_entry.configure(state=state)

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
            val_lbl = ctk.CTkLabel(
                row, text=f"{default:.1f}秒",
                font=ctk.CTkFont(size=12), width=58, anchor="e",
            )
            val_lbl.pack(side="right")

            slider = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=steps)
            slider.set(default)
            slider.pack(fill="x", padx=14, pady=(2, 0))

            def _on_slide(v, lbl=val_lbl, k=key):
                lbl.configure(text=f"{v:.1f}秒")
                self._save_timing()

            slider.configure(command=_on_slide)
            self._sliders[key] = slider

    def _save_timing(self):
        s = self._cfg.setdefault("settings", {})
        s["trigger_delay_sec"]  = round(self._sliders["trigger_delay_sec"].get(), 2)
        s["cooldown_sec"]       = round(self._sliders["cooldown_sec"].get(), 2)
        s["check_interval_sec"] = round(self._sliders["check_interval_sec"].get(), 2)
        save_config(self._cfg)

    # ── 監視トグル ────────────────────────────────────────────────────────

    def _on_toggle(self):
        if self._switch.get():
            self._start_monitoring()
        else:
            self._stop_monitoring()

    def _start_monitoring(self):
        self._face_count = 0
        self._cam_error = False
        self._stop_evt.clear()
        self._monitoring = True
        threading.Thread(target=self._monitor_loop, daemon=True).start()

    def _stop_monitoring(self):
        self._stop_evt.set()
        self._monitoring = False

    def _monitor_loop(self):
        cfg = load_config()
        st = cfg.get("settings", {})

        interval   = st.get("check_interval_sec", 1.0)
        cooldown   = st.get("cooldown_sec", 15)
        trig_delay = st.get("trigger_delay_sec", 2.0)
        min_face   = tuple(st.get("min_face_size", [60, 60]))
        scale      = st.get("scale_factor", 1.1)
        min_nb     = st.get("min_neighbors", 5)
        photo_dir  = str(Path(st.get("screenshot_dir", "~/ShoulderGuard/captures")).expanduser())

        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        cap = cv2.VideoCapture(st.get("camera_index", 0))

        if not cap.isOpened():
            self._cam_error = True
            return

        multi_since = None
        last_trig = 0.0

        while not self._stop_evt.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(interval)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(
                gray, scaleFactor=scale, minNeighbors=min_nb, minSize=min_face
            )
            fc = len(faces)
            self._face_count = fc

            if not self._frame_q.full():
                self._frame_q.put_nowait((frame.copy(), list(faces)))

            now = time.time()
            if fc >= 2:
                if multi_since is None:
                    multi_since = now
                elif now - multi_since >= trig_delay and now - last_trig >= cooldown:
                    last_trig = now
                    multi_since = None
                    self._last_alert = datetime.now()
                    self._do_actions(cfg, frame, photo_dir)
            else:
                multi_since = None

            time.sleep(interval)

        cap.release()

    def _do_actions(self, cfg: dict, frame, photo_dir: str):
        a = cfg.get("actions", {})
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

    # ── UI 定期更新（500ms ごと）──────────────────────────────────────────

    def _poll(self):
        # ステータスラベル
        if self._cam_error:
            self._status_lbl.configure(
                text="カメラエラー（権限を確認してください）",
                text_color="#e74c3c",
            )
        elif self._monitoring:
            fc = self._face_count
            if fc == 0:
                self._status_lbl.configure(
                    text="👁  顔を検出していません",
                    text_color=("gray50", "gray60"),
                )
            elif fc == 1:
                self._status_lbl.configure(
                    text="👤  正常（1人）", text_color="#27ae60",
                )
            else:
                self._status_lbl.configure(
                    text=f"⚠️  第三者を検出！（{fc}人）",
                    text_color="#e67e22",
                )
        else:
            self._status_lbl.configure(
                text="停止中", text_color=("gray50", "gray60"),
            )

        if self._last_alert:
            ts = self._last_alert.strftime("%H:%M:%S")
            note = f"  📸 {Path(self._last_photo).name}" if self._last_photo else ""
            self._alert_lbl.configure(text=f"最終アラート: {ts}{note}")

        # プレビューウィンドウが開いていればフレーム描画
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
        pw.geometry("500x400")
        pw.resizable(False, False)
        self._preview_win = pw

        self._preview_img_lbl = ctk.CTkLabel(pw, text="")
        self._preview_img_lbl.pack(expand=True, fill="both", padx=12, pady=(12, 4))

        self._preview_info = ctk.CTkLabel(
            pw, text="起動中...",
            font=ctk.CTkFont(size=12),
            text_color=("gray55", "gray55"),
        )
        self._preview_info.pack(pady=(0, 10))

        # 監視中でなければ専用スレッドでカメラを開く
        if not self._monitoring:
            threading.Thread(target=self._preview_only_loop, daemon=True).start()

    def _preview_only_loop(self):
        cfg = load_config()
        st = cfg.get("settings", {})
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        cap = cv2.VideoCapture(st.get("camera_index", 0))
        if not cap.isOpened():
            return

        scale  = st.get("scale_factor", 1.1)
        min_nb = st.get("min_neighbors", 5)
        min_fs = tuple(st.get("min_face_size", [60, 60]))

        while (
            self._preview_win
            and self._preview_win.winfo_exists()
            and not self._monitoring
        ):
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scale, min_nb, minSize=min_fs)
            if not self._frame_q.full():
                self._frame_q.put_nowait((frame.copy(), list(faces)))
            time.sleep(0.08)

        cap.release()

    def _refresh_preview_frame(self):
        try:
            frame, faces = self._frame_q.get_nowait()
        except queue.Empty:
            return

        alert = len(faces) >= 2
        color = (30, 30, 220) if alert else (30, 200, 30)
        for x, y, w, h in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(frame_rgb).resize((476, 340), Image.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(476, 340))

        self._preview_img_lbl.configure(image=ctk_img, text="")
        self._preview_img_ref = ctk_img  # GC 防止

        fc = len(faces)
        if alert:
            self._preview_info.configure(
                text=f"⚠️  {fc}人を検出", text_color="#e67e22"
            )
        else:
            self._preview_info.configure(
                text=f"👤 {fc}人" if fc else "顔を検出中...",
                text_color=("gray55", "gray55"),
            )

    # ── 終了 ──────────────────────────────────────────────────────────────

    def _on_close(self):
        self._stop_monitoring()
        self.quit()


# ── エントリーポイント ────────────────────────────────────────────────────

if __name__ == "__main__":
    App().mainloop()
