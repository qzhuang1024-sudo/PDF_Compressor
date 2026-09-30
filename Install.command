#!/bin/bash
# ------------------------------------------------------------------
#  PDF Compressor — macOS 安裝工具
#  雙擊此檔即可安裝：Homebrew → Ghostscript → Python → .venv → Flask
#  可重複執行：已安裝的項目會直接略過，不會重裝。
# ------------------------------------------------------------------

set -u
cd "$(dirname "$0")" || exit 1
APP_DIR="$(pwd)"
VENV="$APP_DIR/.venv"

# 結束時（成功或失敗）都等使用者按 Enter，Terminal 視窗不會瞬間關閉
trap 'echo; read -r -p "Press Enter to close..." _' EXIT

G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; B=$'\033[1m'; N=$'\033[0m'
ok()   { echo "${G}[OK]${N} $*"; echo; }
info() { echo "     $*"; }
fail() {
    echo
    echo "${R}[ERROR] $1${N}"
    shift
    for line in "$@"; do echo "        $line"; done
    echo
    echo "安裝未完成（Installation NOT completed）。"
    exit 1
}
ask_yes() {  # ask_yes "問題" 預設Y/N
    local ans
    read -r -p "$1 " ans
    ans="${ans:-$2}"
    [[ "$ans" =~ ^[Yy] ]]
}

clear
echo "${B}===================================="
echo " PDF Compressor Installation"
echo "====================================${N}"
echo "資料夾：$APP_DIR"
echo "Mac：$(sw_vers -productName 2>/dev/null) $(sw_vers -productVersion 2>/dev/null)（$(uname -m)）"
echo

# 從網路下載的檔案會被加上 quarantine 標記；清掉本資料夾的標記，之後雙擊啟動檔不會再被擋
xattr -dr com.apple.quarantine "$APP_DIR" 2>/dev/null
chmod +x "$APP_DIR"/*.command 2>/dev/null

# ------------------------------------------------------------------
echo "${B}[1/5] Checking Homebrew...${N}"
# 雙擊 .command 時 PATH 可能沒有 brew，所以也檢查 Homebrew 的標準位置
find_brew() {
    command -v brew 2>/dev/null && return
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        [ -x "$b" ] && { echo "$b"; return; }
    done
}
BREW="$(find_brew)"

if [ -z "$BREW" ]; then
    echo "${Y}找不到 Homebrew（macOS 套件管理工具，用來安裝 Ghostscript 與 Python）。${N}"
    info "將使用 Homebrew 官方安裝方式：https://brew.sh"
    info "安裝過程會要求輸入這台 Mac 的登入密碼（輸入時畫面不會顯示字元），"
    info "也可能需要安裝 Apple 的 Command Line Tools，約需 5–15 分鐘。"
    echo
    ask_yes "要安裝 Homebrew 嗎？ Install Homebrew now? [y/N]" N \
        || fail "Homebrew is required." "請重新執行 Install.command 並選擇安裝，或先自行從 https://brew.sh 安裝。"

    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
        || fail "Homebrew installation failed." "請檢查網路連線與管理員密碼後再試一次。"
    BREW="$(find_brew)"
    [ -n "$BREW" ] || fail "Homebrew installation failed." "安裝後仍找不到 brew 指令。"

    # 讓之後自己開的 Terminal 也找得到 brew（Homebrew 官方建議的設定）
    LINE="eval \"\$($BREW shellenv)\""
    grep -qsF "$LINE" "$HOME/.zprofile" || echo "$LINE" >> "$HOME/.zprofile"
fi

eval "$("$BREW" shellenv)"                 # 設定 PATH（不寫死 /opt/homebrew 或 /usr/local）
BREW_PREFIX="$(brew --prefix)"
brew --version >/dev/null 2>&1 || fail "Homebrew does not work." "請執行 brew doctor 查看原因。"
info "$(brew --version | head -1)"
info "Prefix: $BREW_PREFIX"
ok "Homebrew"

# ------------------------------------------------------------------
echo "${B}[2/5] Checking Ghostscript...${N}"
if ! command -v gs >/dev/null 2>&1; then
    info "未安裝，執行：brew install ghostscript（需要網路，約 1–3 分鐘）"
    brew install ghostscript \
        || fail "Ghostscript installation failed." "Please check your internet connection and try again."
    hash -r
fi
GS_VERSION="$(gs --version 2>/dev/null)" \
    || fail "Ghostscript does not work." "請執行 brew reinstall ghostscript 後再試。"
info "Ghostscript: OK"
info "Version: $GS_VERSION"
info "Path: $(command -v gs)"
ok "Ghostscript"

# ------------------------------------------------------------------
echo "${B}[3/5] Checking Python...${N}"
# 使用 Homebrew 的 Python，不使用 macOS 系統內建的 /usr/bin/python3
PY="$BREW_PREFIX/bin/python3"
if [ ! -x "$PY" ]; then
    info "未安裝 Homebrew Python，執行：brew install python"
    brew install python \
        || fail "Python installation failed." "Please check your internet connection and try again."
fi
[ -x "$PY" ] || fail "Python 3 not found." "預期位置：$PY"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || fail "Python 版本太舊（需要 3.9 以上）。" "請執行 brew upgrade python 後再試。"
info "$("$PY" --version)  ($PY)"
ok "Python"

# ------------------------------------------------------------------
echo "${B}[4/5] Creating virtual environment...${N}"
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c 'import sys' >/dev/null 2>&1; then
    info "已存在：$VENV"
else
    rm -rf "$VENV"
    "$PY" -m venv "$VENV" \
        || fail "Virtual environment creation failed." "請確認此資料夾可以寫入：$APP_DIR"
    info "已建立：$VENV"
fi
ok "Virtual environment"

# ------------------------------------------------------------------
echo "${B}[5/5] Installing Python packages...${N}"
"$VENV/bin/python" -m pip install --upgrade pip --quiet --disable-pip-version-check \
    || fail "pip upgrade failed." "Please check your internet connection and try again."
"$VENV/bin/python" -m pip install -r "$APP_DIR/requirements.txt" --quiet --disable-pip-version-check \
    || fail "Python package installation failed." "Please check your internet connection and try again."
ok "Python packages"

# ------------------------------------------------------------------
echo "${B}Verifying installation...${N}"
check() {  # check "名稱" 指令...
    local name="$1"; shift
    if out="$("$@" 2>&1)"; then
        printf "%-15s: ${G}OK${N}   %s\n" "$name" "$(echo "$out" | head -1)"
    else
        printf "%-15s: ${R}FAILED${N}\n" "$name"
        FAILED="$FAILED $name"
    fi
}
FAILED=""
echo
echo "${B}===================================="
echo " PDF Compressor Installation"
echo "====================================${N}"
echo
check "Homebrew"     brew --version
check "Python"       "$VENV/bin/python" --version
check "Virtual Env"  test -x "$VENV/bin/python"
check "Flask"        "$VENV/bin/python" -c "import importlib.metadata as m; print(m.version('flask'))"
check "Ghostscript"  gs --version
check "App files"    "$VENV/bin/python" -c "import compressor, app"
echo

[ -z "$FAILED" ] || fail "以下項目檢查失敗：$FAILED" \
    "請重新執行 Install.command；若仍失敗，請把此視窗的內容截圖給提供工具的人。"

echo "${G}${B}Installation completed successfully.${N}"
echo
echo "之後使用：雙擊「Start PDF Compressor.command」"
echo

if ask_yes "Do you want to start PDF Compressor now? [Y/n]" Y; then
    trap - EXIT
    exec "$APP_DIR/Start PDF Compressor.command"
fi
