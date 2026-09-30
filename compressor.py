"""
compressor.py — 用 Ghostscript 壓縮 PDF（PDF Compressor 的核心）

Ghostscript 參數沿用原本的 壓縮pdf範例.py：
    pdfwrite + CompatibilityLevel 1.4 + PDFSETTINGS + NOPAUSE / QUIET / BATCH
另外可選擇自訂圖片解析度（DPI）與 JPEG 品質。

也可以單獨在命令列使用：
    python compressor.py 檔案.pdf [screen|ebook|printer|prepress]
"""

import glob
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

PRESETS = ("screen", "ebook", "printer", "prepress")


def find_ghostscript():
    """
    找 Ghostscript 執行檔。原本程式直接呼叫 "gswin64c"（需要在 PATH 裡），這裡擴充成：
      Windows：先找 PATH 的 gswin64c，再找 C:\\Program Files\\gs\\gs*\\bin\\gswin64c.exe（不寫死版本）
      macOS  ：先找 PATH 的 gs，再找 /opt/homebrew/bin/gs、/usr/local/bin/gs
    找不到回傳 None。
    """
    if platform.system() == "Windows":
        for name in ("gswin64c", "gswin32c"):
            if shutil.which(name):
                return shutil.which(name)
        found = []
        for base in {os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")}:
            found += glob.glob(os.path.join(base, "gs", "gs*", "bin", "gswin64c.exe"))
            found += glob.glob(os.path.join(base, "gs", "gs*", "bin", "gswin32c.exe"))

        def version(path):  # 用數字比較：gs10.04.0 比 gs9.56.1 新
            m = re.search(r"gs(\d+(?:\.\d+)*)", path)
            return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)

        found.sort(key=version, reverse=True)
        return found[0] if found else None

    if shutil.which("gs"):
        return shutil.which("gs")
    for path in ("/opt/homebrew/bin/gs", "/usr/local/bin/gs", "/opt/local/bin/gs", "/usr/bin/gs"):
        if os.path.isfile(path):
            return path
    return None


def compress_pdf(input_pdf, output_pdf, preset="ebook", dpi=None, jpeg_quality=None,
                 gs=None, timeout=900):
    """
    用 Ghostscript 壓縮 input_pdf，寫出 output_pdf（不會修改 input_pdf）。

    preset       : "screen" / "ebook" / "printer" / "prepress"  → -dPDFSETTINGS=/...
    dpi          : 圖片解析度（彩色、灰階圖片）。None = 使用 preset 預設值
    jpeg_quality : JPEG 品質 1–100。None = 使用 preset 預設值
    回傳 dict：original / compressed（bytes）、seconds（Ghostscript 實際執行秒數）
    失敗時丟出 RuntimeError（訊息可直接顯示給使用者）。
    """
    input_pdf, output_pdf = Path(input_pdf), Path(output_pdf)
    if input_pdf.resolve() == output_pdf.resolve():
        raise RuntimeError("輸出檔不能與原始檔相同。")
    if preset not in PRESETS:
        raise RuntimeError(f"未知的壓縮等級：{preset}")

    gs = gs or find_ghostscript()
    if not gs:
        raise RuntimeError("找不到 Ghostscript，請先安裝後再試一次。")

    # ── 原本的核心參數（完全保留）──
    cmd = [
        gs,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        f"-dPDFSETTINGS=/{preset}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
    ]

    # ── 新增：自訂圖片解析度 ──
    if dpi:
        dpi = int(max(30, min(int(dpi), 1200)))
        cmd += [
            "-dDownsampleColorImages=true", f"-dColorImageResolution={dpi}",
            "-dDownsampleGrayImages=true", f"-dGrayImageResolution={dpi}",
            "-dColorImageDownsampleType=/Bicubic", "-dGrayImageDownsampleType=/Bicubic",
            # 預設只有圖片超過目標 1.5 倍才降解析度；設 1.0 讓設定值確實生效
            "-dColorImageDownsampleThreshold=1.0", "-dGrayImageDownsampleThreshold=1.0",
        ]

    # ── 新增：自訂 JPEG 品質 ──
    ps_params = None
    if jpeg_quality:
        q = int(max(1, min(int(jpeg_quality), 100)))
        # 1–100 的品質 → Ghostscript/Adobe 的 QFactor（IJG 對照：75 ≈ 0.5，50 ≈ 1.0）
        qfactor = (5000 / q if q < 50 else 200 - 2 * q) / 100
        qfactor = max(qfactor, 0.02)
        cmd += [
            "-dPassThroughJPEGImages=false",      # 原本就是 JPEG 的圖也重新壓縮，品質設定才有效
            "-dAutoFilterColorImages=false", "-dColorImageFilter=/DCTEncode",
            "-dAutoFilterGrayImages=false", "-dGrayImageFilter=/DCTEncode",
        ]
        d = f"<< /QFactor {qfactor:.3f} /Blend 1 /HSamples [2 1 1 2] /VSamples [2 1 1 2] >>"
        ps_params = f"<< /ColorImageDict {d} /GrayImageDict {d} >> setdistillerparams"

    cmd.append(f"-sOutputFile={output_pdf}")
    if ps_params:
        cmd += ["-c", ps_params, "-f"]
    cmd.append(str(input_pdf))

    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}
    start = time.perf_counter()
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, **extra)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"壓縮超過 {timeout} 秒，已停止。")
    elapsed = time.perf_counter() - start

    if r.returncode != 0 or not output_pdf.exists() or output_pdf.stat().st_size == 0:
        msg = (r.stderr or r.stdout).decode("utf-8", "replace")
        if "password" in msg.lower() or "encrypt" in msg.lower():
            raise RuntimeError("此 PDF 有密碼保護，無法壓縮。")
        raise RuntimeError("Ghostscript 無法處理此檔案（可能已損壞）。\n" + msg[-400:])

    # Ghostscript 修復損壞檔時仍會回傳 0，但會印出 "**** Error"：當作警告回報
    log = (r.stderr + r.stdout).decode("utf-8", "replace")
    warning = "Ghostscript 回報錯誤，輸出可能不完整，請檢查結果。" if "**** Error" in log else ""

    return {
        "warning": warning,
        "original": input_pdf.stat().st_size,
        "compressed": output_pdf.stat().st_size,
        "seconds": round(elapsed, 2),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法：python compressor.py 檔案.pdf [screen|ebook|printer|prepress]")
        sys.exit(1)
    input_pdf = Path(sys.argv[1])
    preset = sys.argv[2] if len(sys.argv) > 2 else "ebook"
    output_pdf = input_pdf.with_name(input_pdf.stem + "_compressed.pdf")

    result = compress_pdf(input_pdf, output_pdf, preset=preset)

    original = result["original"] / 1024**2
    compressed = result["compressed"] / 1024**2
    print(f"Output:     {output_pdf}")
    print(f"Original:   {original:.2f} MB")
    print(f"Compressed: {compressed:.2f} MB")
    print(f"Reduction:  {(1 - compressed/original) * 100:.1f}%")
    print(f"Time:       {result['seconds']:.2f} s")
    if result["warning"]:
        print(result["warning"])
