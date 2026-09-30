// 所有動作只和本機的 127.0.0.1 溝通，沒有任何外部網路請求
const $ = (s) => document.querySelector(s);
const files = [];            // { file, html }
let busy = false;
let suffixEdited = false;

// ── 後綴：預設 _compressed_YYYYMMDD_HHMMSS ──
function stamp() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_` +
         `${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}
function cleanSuffix(s) {       // 與後端相同的安全處理，只用於預覽
  return s.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").replace(/\.pdf$/i, "").trim();
}
function updateExample() {
  const first = files[0] ? files[0].file.name.replace(/\.pdf$/i, "") : "paper";
  $("#example").textContent = `${first}${cleanSuffix($("#suffix").value) || "_compressed"}.pdf`;
}
$("#suffix").value = "_compressed_" + stamp();
$("#suffix").addEventListener("input", () => { suffixEdited = true; updateExample(); });

// ── 輸出資料夾：空白＝預設；記住上次的選擇（只存在這台電腦的瀏覽器）──
const outdir = $("#outdir");
try { outdir.value = localStorage.getItem("pdfc-outdir") || ""; } catch (e) {}
function saveDir() { try { localStorage.setItem("pdfc-outdir", outdir.value.trim()); } catch (e) {} }
outdir.addEventListener("change", saveDir);
$("#resetdir").addEventListener("click", () => { outdir.value = ""; saveDir(); });
// 開啟本機「選擇資料夾」視窗；回傳選到的路徑，按取消回傳 null
async function chooseFolder() {
  const btn = $("#browse"); btn.disabled = true; btn.textContent = "選擇中…";
  try {
    const fd = new FormData(); fd.append("current", outdir.value.trim() || outdir.dataset.default);
    const d = await (await fetch("/choose-folder", { method: "POST", body: fd })).json();
    if (d.error) { alert(d.error); return null; }
    if (!d.path) return null;
    outdir.value = d.path; saveDir();
    return d.path;
  } catch (e) { alert("無法開啟選擇資料夾視窗"); return null; }
  finally { btn.disabled = false; btn.textContent = "Browse…"; }
}
$("#browse").addEventListener("click", chooseFolder);

// 「按 Compress 時選擇儲存位置」的勾選狀態也記住
const ask = $("#ask");
try { const v = localStorage.getItem("pdfc-ask"); if (v !== null) ask.checked = v === "1"; } catch (e) {}
ask.addEventListener("change", () => { try { localStorage.setItem("pdfc-ask", ask.checked ? "1" : "0"); } catch (e) {} });

// ── 壓縮設定：只有 Custom 可改解析度/品質 ──
const PRESET_DPI = { screen: 72, ebook: 150, printer: 300, prepress: 300 };
function updatePreset() {
  const custom = $("#preset").value === "custom";
  $("#dpi").disabled = $("#quality").disabled = !custom;
  if (!custom) $("#dpi").value = PRESET_DPI[$("#preset").value];
}
$("#preset").addEventListener("change", updatePreset);
function clampInput(el, min, max, def) {
  el.addEventListener("change", () => {
    const v = Math.round(Number(el.value));
    el.value = Number.isFinite(v) && el.value !== "" ? Math.min(max, Math.max(min, v)) : def;
  });
}
clampInput($("#dpi"), 30, 1200, 150);
clampInput($("#quality"), 1, 100, 75);

// ── 檔案清單 ──
const mb = (b) => b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : (b / 1024).toFixed(0) + " KB";
const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function addFiles(list) {
  for (const f of list) {
    if (!/\.pdf$/i.test(f.name)) { alert("只接受 PDF，已略過：" + f.name); continue; }
    if (files.some((x) => x.file.name === f.name && x.file.size === f.size)) continue;
    files.push({ file: f, html: "" });
  }
  render();
}

function render() {
  $("#files").hidden = files.length === 0;
  $("#list").innerHTML = files.map((x, i) => `
    <li><div class="line">
      <span class="name">${esc(x.file.name)}</span>
      <span class="size">${mb(x.file.size)}</span>
      ${busy ? "" : `<button data-remove="${i}">Remove</button>`}
    </div>${x.html ? `<div class="result">${x.html}</div>` : ""}</li>`).join("");
  $("#go").disabled = busy || files.length === 0;
  $("#go").textContent = busy ? "Compressing…" : "Compress PDF";
  updateExample();
}

$("#list").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.remove !== undefined) { files.splice(Number(b.dataset.remove), 1); render(); }
  if (b.dataset.open) fetch(`/open/${b.dataset.open}/${b.dataset.id}`, { method: "POST" });
});

// ── 拖曳 / 點擊選檔 ──
const drop = $("#drop");
drop.addEventListener("click", () => $("#picker").click());
$("#picker").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
// 放在拖曳區外時，不要讓瀏覽器直接打開 PDF
["dragover", "drop"].forEach((t) => window.addEventListener(t, (e) => e.preventDefault()));

// ── 壓縮：逐一處理 ──
$("#go").addEventListener("click", async () => {
  if (ask.checked) {
    $("#go").disabled = true; $("#go").textContent = "請選擇儲存位置…";
    const picked = await chooseFolder();
    if (!picked) { render(); return; }          // 按取消：不壓縮
  }
  if (!suffixEdited) $("#suffix").value = "_compressed_" + stamp();   // 未修改過就更新成現在時間
  busy = true;
  for (const x of files) x.html = "Waiting…";
  render();

  for (const x of files) {
    x.html = "Compressing…"; render();
    const fd = new FormData();
    fd.append("file", x.file);
    fd.append("suffix", $("#suffix").value);
    fd.append("outdir", outdir.value);
    fd.append("preset", $("#preset").value);
    fd.append("dpi", $("#dpi").value);
    fd.append("quality", $("#quality").value);
    try {
      const r = await fetch("/compress", { method: "POST", body: fd });
      const d = await r.json().catch(() => ({ error: `伺服器錯誤（${r.status}）` }));
      if (!r.ok) throw new Error(d.error || "壓縮失敗");
      const pct = (100 * (1 - d.compressed / d.original)).toFixed(1);
      const change = d.compressed < d.original
        ? `<span class="ok">Reduction: ${pct}%</span>`
        : `<span class="warn">壓縮後檔案沒有變小，建議保留原檔</span>`;
      const n = esc(d.name), id = esc(d.id);
      const warn = d.warning ? `<br><span class="err">⚠ ${esc(d.warning)}</span>` : "";
      x.html = `${mb(d.original)} → ${mb(d.compressed)} · ${change} · ${d.seconds.toFixed(2)} s<br>
        → <span title="${esc(d.folder)}">${esc(d.folder)}${d.folder.includes("/") ? "/" : "\\"}${n}</span><br>
        <button class="link" data-open="file" data-id="${id}">Open PDF</button>
        <button class="link" data-open="folder" data-id="${id}">Open folder</button>
        <a href="/download/${id}">Download</a>${warn}`;
    } catch (err) {
      x.html = `<span class="err">${esc(err.message)}</span>`;
    }
    render();
  }
  busy = false; render();
});

updatePreset();
render();

// ── 告訴本機程式「頁面還開著」；關掉分頁後程式會自動結束 ──
setInterval(() => fetch("/ping").catch(() => {}), 10000);
$("#quit").addEventListener("click", async () => {
  if (busy && !confirm("正在壓縮中，確定要結束嗎？")) return;
  await fetch("/quit", { method: "POST" }).catch(() => {});
  document.body.innerHTML = '<main><h1>PDF Compressor 已結束</h1><p class="sub">可以關閉此分頁。下次請再雙擊啟動檔（Mac：Start PDF Compressor.command；Windows：Start PDF Compressor (Windows).pyw）。</p></main>';
});
