#!/bin/bash
# ===========================================================
#  build_app.sh  —  ShoulderGuard.app を作成して /Applications へコピー
#
#  戦略: プロジェクトの .venv をそのまま .app 内に同梱する。
#        ランチャーは Homebrew Python の絶対パスで直接起動。
#        runtime でのパッケージビルドは一切行わない。
# ===========================================================
set -euo pipefail

APP_NAME="ShoulderGuard"
BUNDLE="${APP_NAME}.app"
MACOS="${BUNDLE}/Contents/MacOS"
RESOURCES="${BUNDLE}/Contents/Resources"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# プロジェクト venv の Python 実体を特定
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python3"
if [ ! -f "${VENV_PYTHON}" ]; then
    echo "❌ .venv が見つかりません。先に run_gui.sh を一度実行してください。"
    exit 1
fi
# シンボリックリンクを解決して実体 Python パスを取得
REAL_PYTHON="$(cd "$(dirname "${VENV_PYTHON}")" && pwd -P)/$(readlink "${VENV_PYTHON}" || basename "${VENV_PYTHON}")"
# さらに python3.14 -> 実体を解決
REAL_PYTHON="$(cd "$(dirname "${REAL_PYTHON}")" && readlink -f "${REAL_PYTHON}" 2>/dev/null || echo "${REAL_PYTHON}")"
echo "  使用 Python: ${REAL_PYTHON}"

echo "=== ShoulderGuard.app ビルド ==="

# ── 既存バンドルを削除 ────────────────────────────────────────────────────
rm -rf "${BUNDLE}"
mkdir -p "${MACOS}" "${RESOURCES}/face_data"

# ── プロジェクトファイルをコピー ──────────────────────────────────────────
cp shoulder_guard_gui.py "${RESOURCES}/"
cp shoulder_guard.py     "${RESOURCES}/"
cp config.yaml           "${RESOURCES}/"
cp requirements.txt      "${RESOURCES}/"

# ── venv を同梱（dlib 等ビルド済みのものをそのまま使用）──────────────────
# cmake はビルドツールなので実行時不要。除外してコピーする。
echo "  venv をコピー中..."
rsync -aq --exclude='cmake/' "${PROJECT_DIR}/.venv/" "${RESOURCES}/.venv/"
echo "  ✓ venv コピー完了"

# ── 顔データを引き継ぐ ────────────────────────────────────────────────────
if [ -f "face_data/owner_encoding.npy" ]; then
    cp face_data/owner_encoding.npy "${RESOURCES}/face_data/"
    echo "  ✓ 顔データを引き継ぎました"
fi

# ── ランチャースクリプト ──────────────────────────────────────────────────
cat > "${MACOS}/${APP_NAME}" << 'LAUNCHER'
#!/bin/bash
RESOURCES="$(cd "$(dirname "$0")/../Resources" && pwd)"
VENV="${RESOURCES}/.venv"
PYTHON="${VENV}/bin/python3"

if [ ! -x "${PYTHON}" ]; then
    osascript -e 'display alert "起動エラー" message "環境が壊れています。build_app.sh を再実行してください。" as critical'
    exit 1
fi

# venv/bin/python3 経由で起動することで pyvenv.cfg が自動認識される
exec "${PYTHON}" "${RESOURCES}/shoulder_guard_gui.py"
LAUNCHER

chmod +x "${MACOS}/${APP_NAME}"

# ── Info.plist ────────────────────────────────────────────────────────────
cat > "${BUNDLE}/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>ShoulderGuard</string>
    <key>CFBundleDisplayName</key>
    <string>ShoulderGuard</string>
    <key>CFBundleIdentifier</key>
    <string>com.shoulderguard.app</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>ShoulderGuard</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSCameraUsageDescription</key>
    <string>顔検出・顔認識のためにカメラを使用します。映像は外部に送信されません。</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
</dict>
</plist>
PLIST

echo ""
echo "✅ ${BUNDLE} を作成しました"
echo ""

# ── /Applications へコピー ────────────────────────────────────────────────
read -r -p "/Applications にコピーしますか？ [y/N]: " answer
if [[ "$answer" =~ ^[Yy]$ ]]; then
    rm -rf "/Applications/${BUNDLE}"
    ditto "${BUNDLE}" "/Applications/${BUNDLE}"
    echo "✅ /Applications/${BUNDLE} にインストールしました"
    echo "   Launchpad または Spotlight で「ShoulderGuard」を検索してください"
else
    echo "   手動でコピーするには:"
    echo "   cp -r ${BUNDLE} /Applications/"
fi
