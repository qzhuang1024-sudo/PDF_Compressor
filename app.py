"""
app.py — 本機 PDF 壓縮工具的瀏覽器介面

使用方式：macOS 雙擊「Start PDF Compressor.command」
          Windows 雙擊「Start PDF Compressor (Windows).pyw」
          或  python app.py
會自動開啟 http://127.0.0.1:5000 （只在本機，不連網路）
關閉瀏覽器分頁後，程式會在幾分鐘內自動結束；也可按頁面上的「結束程式」。

壓縮邏輯全部來自 compressor.py 的 compress_pdf()，這裡只負責：
接收瀏覽器拖進來的 PDF → 存成暫存檔 → 呼叫 compress_pdf() → 把結果存到本資料夾
"""

import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import sys
import uuid
import urllib.request
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from compressor import PRESETS, compress_pdf, find_ghostscript

# 預設輸出位置：本工具所在的資料夾（網頁上可另外指定）
OUTPUT_DIR = Path(__file__).resolve().parent
produced = {}                                           # id → 本次產生的輸出檔路徑

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024**3          # 單檔上限 2 GB
gs_lock = threading.Lock()                              # 一次只跑一個 Ghostscript
last_seen = time.time()                                 # 瀏覽器最後一次回報「還開著」的時間
IDLE_EXIT_SEC = 180                                     # 頁面關閉超過 3 分鐘 → 自動結束
APP_ID = "pdf-compressor"
BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_part(text):
    """移除路徑與 Windows/macOS 不允許的字元（保留中文）。"""
    text = BAD.sub("_", text.replace("\\", "/").split("/")[-1])
    return text.strip(" .")


def resolve_folder(text):
    """使用者指定的輸出資料夾；空白 = 本工具所在資料夾。不合法時丟出 RuntimeError。"""
    text = (text or "").strip().strip('"')
    if not text:
        return OUTPUT_DIR
    folder = Path(os.path.expandvars(os.path.expanduser(text)))
    if not folder.is_absolute():
        raise RuntimeError("輸出資料夾請填完整路徑，例如 C:\\Users\\你的名字\\Desktop")
    if not folder.is_dir():
        raise RuntimeError(f"找不到輸出資料夾：{folder}")
    return folder.resolve()


def output_path(original_name, suffix, folder):
    """原檔名 + suffix + .pdf；已存在就加 _1、_2…，絕不覆蓋任何檔案。"""
    stem = safe_part(original_name)
    stem = re.sub(r"\.pdf$", "", stem, flags=re.I) or "document"
    suffix = re.sub(r"\.pdf$", "", safe_part(suffix), flags=re.I) or "_compressed"
    base = (stem + suffix)[:200]
    n = 0
    while True:
        path = folder / (f"{base}.pdf" if n == 0 else f"{base}_{n}.pdf")
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))  # 原子性佔位
            return path
        except FileExistsError:
            n += 1


@app.get("/")
def index():
    return render_template("index.html", gs=find_ghostscript(), output_dir=OUTPUT_DIR)


@app.post("/compress")
def compress():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".pdf"):
        return jsonify(error="不是 PDF 檔案。"), 400

    preset = request.form.get("preset", "ebook")
    custom = preset == "custom"
    if not custom and preset not in PRESETS:
        return jsonify(error="壓縮等級不正確。"), 400
    try:
        dpi = int(request.form["dpi"]) if custom else None
        quality = int(request.form["quality"]) if custom else None
    except (KeyError, ValueError):
        return jsonify(error="圖片解析度 / 品質必須是數字。"), 400
    if custom and not (30 <= dpi <= 1200 and 1 <= quality <= 100):
        return jsonify(error="解析度需介於 30–1200 DPI，品質需介於 1–100。"), 400

    try:
        folder = resolve_folder(request.form.get("outdir"))
    except RuntimeError as e:
        return jsonify(error=str(e)), 400

    tmp = Path(tempfile.mkdtemp(prefix="pdfc_"))
    src, out = tmp / "in.pdf", tmp / "out.pdf"   # 英文暫存路徑，Ghostscript 最穩定
    try:
        f.save(src)                               # 串流寫到磁碟，不整個讀進記憶體
        with open(src, "rb") as fh:
            if b"%PDF-" not in fh.read(1024):
                return jsonify(error="檔案內容不是有效的 PDF。"), 400

        with gs_lock:
            result = compress_pdf(src, out, preset="ebook" if custom else preset,
                                  dpi=dpi, jpeg_quality=quality)

        dst = output_path(f.filename, request.form.get("suffix", ""), folder)
        try:
            os.replace(out, dst)
        except OSError:
            shutil.copyfile(out, dst)             # 暫存與輸出在不同磁碟時
        file_id = uuid.uuid4().hex
        produced[file_id] = dst                   # 只有本工具產生的檔案可以被下載 / 開啟
        return jsonify(id=file_id, name=dst.name, folder=str(folder), **result)
    except RuntimeError as e:
        return jsonify(error=str(e)), 422
    except PermissionError:
        return jsonify(error=f"沒有權限寫入資料夾：{folder}"), 500
    except OSError as e:
        return jsonify(error=f"檔案處理失敗：{e}"), 500
    finally:
        shutil.rmtree(tmp, ignore_errors=True)    # 刪除暫存檔


def _checked(file_id):
    """只允許開啟 / 下載本工具這次產生的檔案（防止 path traversal）。"""
    path = produced.get(file_id)
    if not path or not path.is_file():
        abort(404)
    return path


@app.get("/download/<file_id>")
def download(file_id):
    path = _checked(file_id)
    return send_file(path, as_attachment=True, download_name=path.name)


@app.post("/open/<what>/<file_id>")
def open_local(what, file_id):
    """在本機開啟 PDF 或顯示所在資料夾（由 Python 在你的電腦上執行）。"""
    path = _checked(file_id)
    system = platform.system()
    if what == "file":
        if system == "Windows":
            os.startfile(path)
        else:
            subprocess.Popen(["open" if system == "Darwin" else "xdg-open", str(path)])
    else:
        if system == "Windows":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    return jsonify(ok=True)


CHOOSE_FOLDER_TK = r"""
import sys, tkinter
from tkinter import filedialog
root = tkinter.Tk(); root.withdraw(); root.attributes("-topmost", True)
path = filedialog.askdirectory(title="選擇輸出資料夾", initialdir=sys.argv[1] or None, mustexist=True)
sys.stdout.buffer.write((path or "").encode("utf-8"))
"""


CHOOSE_FOLDER_PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = '選擇輸出資料夾'
$d.SelectedPath = $env:PDFC_START
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true}
if ($d.ShowDialog($owner) -eq 'OK') { [Console]::Write($d.SelectedPath) }
"""


@app.post("/choose-folder")
def choose_folder():
    """開啟作業系統的「選擇資料夾」視窗（在本機執行），回傳選到的路徑。"""
    start = (request.form.get("current") or "").strip().strip('"')
    if not start or not Path(start).is_dir():
        start = str(OUTPUT_DIR)
    try:
        if platform.system() == "Darwin":
            script = ['tell me to activate',
                      'set p to POSIX path of (choose folder with prompt "選擇輸出資料夾" '
                      'default location (POSIX file (system attribute "PDFC_START")))',
                      'return p']
            args = ["osascript"] + sum([["-e", line] for line in script], [])
            r = subprocess.run(args, capture_output=True, timeout=600,
                               env={**os.environ, "PDFC_START": start})
            if r.returncode != 0 and b"-128" in r.stderr:   # 使用者按「取消」
                return jsonify(path="")
        else:
            python = Path(sys.executable)
            if python.name.lower() == "pythonw.exe":
                python = python.with_name("python.exe")
            flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            r = subprocess.run([str(python), "-c", CHOOSE_FOLDER_TK, start],
                               capture_output=True, timeout=600, **flags)
            if r.returncode != 0 and os.name == "nt":     # 沒有 tkinter 時改用 Windows 內建視窗
                r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", CHOOSE_FOLDER_PS],
                                   capture_output=True, timeout=600, env={**os.environ, "PDFC_START": start},
                                   **flags)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", "replace")[-300:])
        path = r.stdout.decode("utf-8", "replace").strip()
        return jsonify(path=str(Path(path)) if path else "")
    except Exception as e:
        return jsonify(error=f"無法開啟選擇資料夾視窗：{e}"), 500


@app.get("/ping")
def ping():
    """頁面每隔幾秒呼叫一次，讓程式知道瀏覽器還開著。"""
    global last_seen
    last_seen = time.time()
    return APP_ID


@app.post("/quit")
def quit_app():
    threading.Timer(0.5, os._exit, [0]).start()
    return jsonify(ok=True)


def watchdog():
    """瀏覽器分頁都關掉、且沒有在壓縮時，自動結束程式（背景執行時不會一直殘留）。"""
    while True:
        time.sleep(15)
        if time.time() - last_seen > IDLE_EXIT_SEC and not gs_lock.locked():
            os._exit(0)


def running_instance():
    """若工具已在執行，回傳它的網址（避免重複啟動）。"""
    for port in range(5000, 5011):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=0.5) as r:
                if r.read().decode() == APP_ID:
                    return f"http://127.0.0.1:{port}"
        except Exception:
            pass
    return None


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="檔案太大（上限 2 GB）。"), 413


def main():
    existing = running_instance()
    if existing:                                  # 已經開著：只打開瀏覽器
        webbrowser.open(existing)
        return

    port = 5000
    while True:                                   # 5000 被占用（例如 macOS AirPlay）就往後找
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                break
        port += 1
    url = f"http://127.0.0.1:{port}"
    print("Ghostscript:", find_ghostscript() or "找不到！請先安裝")
    print("輸出資料夾:", OUTPUT_DIR)
    print("已啟動：", url)
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Timer(1.0, webbrowser.open, [url]).start()
    app.run(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
