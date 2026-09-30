"""
Start PDF Compressor (Windows).pyw — Windows 雙擊這個檔案即可使用（.pyw 由 pythonw 執行，不會出現黑色命令視窗）

1. 第一次使用若沒有 Flask，會自動安裝（只需一次，需要網路）
2. 在背景啟動本機伺服器，並自動開啟瀏覽器
3. 若已經在執行，只會再打開瀏覽器
4. 關閉瀏覽器分頁幾分鐘後自動結束，或按頁面上的「結束程式」
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
sys.path.insert(0, str(HERE))

# pythonw 沒有 console：把輸出寫到暫存資料夾的紀錄檔（出問題時可查看）
log = open(Path(tempfile.gettempdir()) / "pdf_compressor.log", "a", encoding="utf-8")
sys.stdout = sys.stderr = log


def message(title, text, error=False):
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title, text)
        root.destroy()
    except Exception:
        print(title, text)


try:
    import flask  # noqa: F401
except ImportError:
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe":          # pip 用一般的 python.exe 執行
        python = python.with_name("python.exe")
    r = subprocess.run([str(python), "-m", "pip", "install", "--user", "flask"],
                       capture_output=True, text=True, **flags)
    if r.returncode != 0:
        message("PDF 壓縮工具", "無法自動安裝 Flask。\n\n請手動執行：pip install flask\n\n"
                + r.stderr[-500:], error=True)
        sys.exit(1)
    import site
    site.addsitedir(site.getusersitepackages())        # 讓剛安裝的套件可以被 import

try:
    import app
    app.main()
except Exception as e:
    import traceback
    traceback.print_exc()
    message("PDF 壓縮工具", f"啟動失敗：{e}", error=True)
