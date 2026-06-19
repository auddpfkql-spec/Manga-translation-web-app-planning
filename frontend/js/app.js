// 만화 번역기 프론트엔드 로직
const fileInput = document.getElementById("file-input");
const fileName = document.getElementById("file-name");
const dropZone = document.getElementById("drop-zone");
const translateBtn = document.getElementById("translate-btn");
const sourceLang = document.getElementById("source-lang");
const statusEl = document.getElementById("status");
const resultSection = document.getElementById("result-section");
const originalImg = document.getElementById("original-img");
const resultImg = document.getElementById("result-img");
const downloadLink = document.getElementById("download-link");

let selectedFile = null;

function setFile(file) {
  if (!file || !file.type.startsWith("image/")) return;
  selectedFile = file;
  fileName.textContent = file.name;
  translateBtn.disabled = false;
  originalImg.src = URL.createObjectURL(file);
}

fileInput.addEventListener("change", (e) => setFile(e.target.files[0]));

// 드래그 앤 드롭
["dragenter", "dragover"].forEach((evt) =>
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((evt) =>
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
  })
);
dropZone.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));

function showStatus(msg, isError = false) {
  statusEl.hidden = false;
  statusEl.textContent = msg;
  statusEl.classList.toggle("error", isError);
}

translateBtn.addEventListener("click", async () => {
  if (!selectedFile) return;

  translateBtn.disabled = true;
  resultSection.hidden = true;
  showStatus("번역 중… (감지 → OCR → 인페인팅 → 번역 → 식자)");

  const form = new FormData();
  form.append("file", selectedFile);
  form.append("options", JSON.stringify({ source_lang: sourceLang.value }));

  try {
    const res = await fetch("/api/translate", { method: "POST", body: form });
    if (!res.ok) throw new Error(`서버 오류 (${res.status})`);
    const data = await res.json();

    resultImg.src = data.result_image;
    downloadLink.href = data.result_image;
    resultSection.hidden = false;

    const blocks = data.blocks?.length ?? 0;
    const total = Object.values(data.timing_ms || {}).reduce((a, b) => a + b, 0);
    showStatus(`완료 · 블록 ${blocks}개 · ${Math.round(total)}ms`);
  } catch (err) {
    showStatus(`실패: ${err.message}`, true);
  } finally {
    translateBtn.disabled = false;
  }
});
