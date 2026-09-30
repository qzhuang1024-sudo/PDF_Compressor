#!/bin/bash
# ------------------------------------------------------------------
#  PDF Compressor — macOS 啟動檔（雙擊即可）
#  會用 .venv 裡的 Python 啟動本機伺服器，並自動開啟瀏覽器。
#  關閉瀏覽器分頁幾分鐘後會自動結束，或按網頁上的「結束程式」。
# ------------------------------------------------------------------

cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
    echo "尚未安裝。請先雙擊「Install.command」。"
    echo
    read -r -p "Press Enter to close..." _
    exit 1
fi

# 讓 Python 找得到 Homebrew 安裝的 gs（不寫死路徑，由 brew shellenv 設定 PATH）
for b in "$(command -v brew)" /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -n "$b" ] && [ -x "$b" ]; then eval "$("$b" shellenv)"; break; fi
done

clear
echo "PDF Compressor 執行中（只在這台 Mac 上處理，不會上傳 PDF）"
echo "瀏覽器會自動開啟。用完請按網頁上的「結束程式」，或直接關閉此視窗。"
echo

.venv/bin/python app.py
status=$?

if [ $status -ne 0 ]; then
    echo
    echo "PDF Compressor 發生錯誤（代碼 $status）。請重新執行 Install.command 再試。"
    read -r -p "Press Enter to close..." _
fi
exit $status
