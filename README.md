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

### 3. アクセシビリティの権限（画面ロックを使う場合）

スクリプトが `Ctrl+Q`（画面ロック）を実行するため、  
**システム設定 → プライバシーとセキュリティ → アクセシビリティ**  
→ ターミナルを許可する

---

## 使い方

```bash
# 監視を開始する
python shoulder_guard.py

# カメラプレビューで顔検出の動作を確認する
python shoulder_guard.py preview

# 設定を対話的に変更する
python shoulder_guard.py config
```

`Ctrl+C` で終了します。

---

## 検出の仕組み

1. カメラで `check_interval_sec` 秒ごとにフレームを取得
2. **2人以上**の顔を検出したらカウント開始
3. `trigger_delay_sec` 秒間**継続して**検出された場合にアクション実行
   （一瞬映り込んだだけでは反応しない）
4. 実行後は `cooldown_sec` 秒間は再トリガーしない

---

## 設定変更（config.yaml）

直接ファイルを編集するか、`python shoulder_guard.py config` で対話的に変更できます。

| 設定キー | 説明 | デフォルト |
|---|---|---|
| `trigger_delay_sec` | 何秒継続検出したらトリガーするか | 2.0 |
| `cooldown_sec` | トリガー後の待機時間（秒） | 15 |
| `check_interval_sec` | 検出間隔（秒） | 1.0 |
| `min_neighbors` | 顔検出の厳しさ（大＝誤検知↓） | 5 |
| `redirect_url` | open_url: true のとき開くURL | https://www.google.com |

### アクション切り替え

```yaml
actions:
  notify: true        # macOS通知
  screenshot: true    # 検出時の顔画像を保存
  play_sound: false   # 警告音
  open_url: false     # 指定URLをブラウザで開く
  lock_screen: true   # 画面をロック（最後に実行）
```

`true` / `false` を書き換えるか、`python shoulder_guard.py config` で変更できます。

---

## 保存された画像

`~/ShoulderGuard/captures/` に `intruder_YYYYMMDD_HHMMSS.jpg` として保存されます。

---

## トラブルシューティング

**カメラが開けない**  
→ カメラの権限をシステム設定で許可してください。

**誤検知が多い**  
→ `config.yaml` の `min_neighbors` を `6〜8` に上げる、または `trigger_delay_sec` を `3〜5` に増やしてください。

**検出が遅い・逃される**  
→ `check_interval_sec` を `0.5` に下げてください。

**画面ロックが動かない**  
→ アクセシビリティ権限をターミナルに付与してください（セットアップ手順3）。
