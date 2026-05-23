# ShoulderGuard

カメラで第三者（のぞき見）を検出し、自動で Mac を守るセキュリティツールです。  
**すべての処理はデバイス上でローカルに完結します。映像・顔データが外部に送信されることはありません。**

---

## プライバシーについて

ShoulderGuard はプライバシーを最優先に設計されています。

| 項目 | 内容 |
|---|---|
| 映像の送信 | **なし** — カメラ映像は外部サーバーに送信されません |
| 顔データの保存先 | **ローカルのみ** — `face_data/owner_encoding.npy`（アプリ内） |
| 顔データの形式 | 128次元の数値ベクトル（顔写真ではない） |
| インターネット接続 | **不要** — オフライン環境でも動作します |
| クラウド連携 | **なし** |

顔エンコーディングは [dlib](http://dlib.net/) を使ってデバイス上で生成・照合されます。`face_data/` フォルダを削除するだけで顔データを完全に消去できます。

---

## 機能

- **顔認識モード**: 自分の顔を登録しておくと、自分が映っていて**かつ別人が映ったとき**にのみアラートを実行
- **フォールバックモード**: 顔認識ライブラリ未使用時は「2人以上検出」でアラート
- **カメラ選択**: 内蔵カメラ / 外部カメラ / iPhone 連係カメラを切り替え可能
- **アクション設定**: 画面ロック・通知・写真保存・警告音・URLリダイレクトを個別にON/OFF
- **GUI アプリ**: macOS のダーク/ライトモードに追従するネイティブ風 UI

---

## 必要なもの

- macOS 12 以降
- Python 3.10 以降（[Homebrew](https://brew.sh) 推奨）
- 内蔵カメラまたは USB カメラ

---

## セットアップ

### 方法 A: .app をダウンロードしてインストール（推奨）

1. [Releases](https://github.com/sdkjp/ShoulderGuard-For-Mac/releases/latest) から `ShoulderGuard-1.0.zip` をダウンロード
2. zip を解凍して `ShoulderGuard.app` を `/Applications` にドラッグ
3. 初回起動時はシステム設定でカメラ・アクセシビリティの権限を許可

> Python や依存ライブラリのインストールは不要です。

### 方法 B: ソースからビルド

```bash
# 依存ライブラリをインストールして GUI を起動（初回は数分かかります）
bash run_gui.sh

# .app をビルドして /Applications にインストール
bash build_app.sh
```

### 方法 C: CLI スクリプトのみ

```bash
pip install opencv-python pyyaml
python shoulder_guard.py
```

---

## 依存ライブラリ

```
opencv-python   # カメラ・顔検出
customtkinter   # GUI フレームワーク
Pillow          # 画像処理
pyyaml          # 設定ファイル読み書き
dlib            # 顔認識エンジン（ローカル処理）
face-recognition
```

---

## 使い方（GUI）

1. アプリを起動し、**「自分の顔を登録する」** をクリック
2. カメラに顔を向けて **「撮影開始」** → 3秒後に自動撮影
3. 登録完了後、**「監視」スイッチ** をオンにする
4. 自分以外の人物が検出されたとき、設定したアクションが実行されます

### カメラの選択

iPhone 連係カメラが使われている場合は、**「タイミング」タブ** の「カメラ」ドロップダウンから内蔵カメラ（FaceTime HD Camera）を選択してください。

> **連係カメラについて**: iPhone を Mac の近くに置くと macOS が自動で iPhone をカメラとして使う場合があります。不要な場合はシステム設定 → 一般 → AirPlay と Handoff → 連係カメラ をオフにしてください。

---

## 使い方（CLI）

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
2. **顔認識モード**: 登録済みの顔（自分）＋未登録の顔が同時に映った場合にカウント開始  
   **フォールバックモード**: 2人以上の顔を検出したらカウント開始
3. `trigger_delay_sec` 秒間**継続して**検出された場合にアクション実行（一瞬映り込んだだけでは反応しない）
4. 実行後は `cooldown_sec` 秒間は再トリガーしない

---

## 設定（config.yaml）

| 設定キー | 説明 | デフォルト |
|---|---|---|
| `camera_index` | 使用するカメラの番号 | 0 |
| `trigger_delay_sec` | 何秒継続検出したらトリガーするか | 2.0 |
| `cooldown_sec` | トリガー後の待機時間（秒） | 15 |
| `check_interval_sec` | 検出間隔（秒） | 1.0 |
| `min_neighbors` | 顔検出の厳しさ（大＝誤検知↓） | 5 |
| `redirect_url` | open_url: true のとき開くURL | https://www.google.com |

### アクション設定

```yaml
actions:
  notify: true        # macOS 通知
  screenshot: true    # 検出時の写真を保存
  play_sound: false   # 警告音
  open_url: false     # 指定 URL をブラウザで開く
  lock_screen: true   # 画面をロック（最後に実行）
```

---

## 保存された写真

`~/ShoulderGuard/captures/` に `intruder_YYYYMMDD_HHMMSS.jpg` として保存されます。

Finder で開く:
```bash
open ~/ShoulderGuard/captures/
```

---

## 権限の設定

### カメラ

システム設定 → プライバシーとセキュリティ → カメラ  
→ ShoulderGuard（またはターミナル）を許可

### アクセシビリティ（画面ロックを使う場合）

システム設定 → プライバシーとセキュリティ → アクセシビリティ  
→ ShoulderGuard（またはターミナル）を許可

---

## トラブルシューティング

**カメラが黒画面になる / 開けない**  
→ カメラ権限をシステム設定で許可してください。iPhone 連係カメラが干渉している場合はタイミングタブでカメラを切り替えてください。

**dlib のビルドに失敗する**  
→ `brew install cmake` を実行してから再試行してください。

**誤検知が多い**  
→ `config.yaml` の `min_neighbors` を `6〜8` に上げる、または `trigger_delay_sec` を `3〜5` に増やしてください。

**検出が遅い・逃される**  
→ `check_interval_sec` を `0.5` に下げてください。

**画面ロックが動かない**  
→ アクセシビリティ権限を付与してください。

---

## ファイル構成

```
.
├── shoulder_guard_gui.py   # GUI アプリ本体
├── shoulder_guard.py       # CLI スクリプト
├── config.yaml             # 設定ファイル
├── run_gui.sh              # GUI 起動スクリプト
├── build_app.sh            # .app ビルドスクリプト
├── requirements.txt        # 依存ライブラリ一覧
└── face_data/
    └── owner_encoding.npy  # 顔エンコーディング（自動生成・ローカルのみ）
```
