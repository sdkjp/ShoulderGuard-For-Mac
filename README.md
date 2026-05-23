# ShoulderGuard

カメラで第三者（のぞき見）を検出し、自動でMacを守るPythonスクリプトです。

---

## 必要なもの

- macOS
- Python 3.8 以上
- 内蔵カメラ（またはUSBカメラ）

---

## セットアップ

### 1. 依存ライブラリをインストール

```bash
pip install opencv-python pyyaml
```

### 2. カメラの権限を許可

**システム設定 → プライバシーとセキュリティ → カメラ**
→ ターミナル（またはPython）にアクセスを許可する

### 3. 画面ロック権限（初回のみ）

スクリプトが `Ctrl+Q`（画面ロック）を実行するため、  
**システム設定 → プライバシーとセキュリティ → アクセシビリティ**  
→ ターミナルを許可する

---

## 使い方

```bash
cd shoulder_guard
python shoulder_guard.py
```

`Ctrl+C` で終了します。

---

## 設定変更（config.yaml）

`config.yaml` を編集してアクションをカスタマイズできます。

| 設定キー | 説明 | デフォルト |
|---|---|---|
| `check_interval_sec` | 検出間隔（秒） | 1.0 |
| `cooldown_sec` | 連続トリガー防止（秒） | 15 |
| `min_neighbors` | 顔検出の厳しさ（大＝誤検知↓） | 5 |
| `show_preview` | カメラ映像をプレビュー表示 | false |

### アクション切り替え

```yaml
actions:
  notify: true        # macOS通知
  screenshot: true    # 顔画像を保存
  play_sound: false   # 警告音
  open_url: false     # 別URLへ移動
  lock_screen: true   # 画面ロック
```

`true` / `false` を書き換えるだけで変更できます。

---

## 保存された画像

`~/ShoulderGuard/captures/` に `intruder_YYYYMMDD_HHMMSS.jpg` として保存されます。

---

## トラブルシューティング

**カメラが開けない**  
→ カメラの権限をシステム設定で許可してください。

**誤検知が多い**  
→ `config.yaml` の `min_neighbors` を `6〜8` に上げてください。

**検出が遅い・逃される**  
→ `check_interval_sec` を `0.5` に下げてください。

**画面ロックが動かない**  
→ アクセシビリティ権限をターミナルに付与してください。
