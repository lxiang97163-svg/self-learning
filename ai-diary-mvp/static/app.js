(() => {
  const $ = id => document.getElementById(id);

  const uploadCard    = $('uploadCard');
  const uploadZone    = $('uploadZone');
  const fileInput     = $('fileInput');
  const photosCard    = $('photosCard');
  const photoGrid     = $('photoGrid');
  const addMoreBtn    = $('addMoreBtn');
  const addMoreInput  = $('addMoreInput');
  const controlsCard  = $('controlsCard');
  const styleSelector = $('styleSelector');
  const generateBtn   = $('generateBtn');
  const resultCard    = $('resultCard');
  const resultText    = $('resultText');
  const resultStyleTag = $('resultStyleTag');
  const copyBtn       = $('copyBtn');
  const regenerateBtn = $('regenerateBtn');
  const resetBtn      = $('resetBtn');

  let photos = [];      // { file, objectUrl, note }
  let selectedStyle = 'healing';
  const styleNames = { healing: '治愈风', literary: '文艺风', humorous: '幽默风' };

  // --- Upload zone interactions ---

  uploadZone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', e => addFiles(e.target.files));

  uploadZone.addEventListener('dragover', e => {
    e.preventDefault();
    uploadZone.classList.add('drag-over');
  });
  uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
  uploadZone.addEventListener('drop', e => {
    e.preventDefault();
    uploadZone.classList.remove('drag-over');
    addFiles(e.dataTransfer.files);
  });

  addMoreBtn.addEventListener('click', () => addMoreInput.click());
  addMoreInput.addEventListener('change', e => addFiles(e.target.files));

  function addFiles(fileList) {
    const incoming = Array.from(fileList).filter(f => f.type.startsWith('image/'));
    const remaining = 20 - photos.length;
    if (remaining <= 0) { showToast('最多上传20张照片'); return; }
    incoming.slice(0, remaining).forEach(file => {
      photos.push({ file, objectUrl: URL.createObjectURL(file), note: '' });
    });
    renderGrid();
    uploadCard.hidden = true;
    photosCard.hidden = false;
    controlsCard.hidden = false;
  }

  // --- Photo grid rendering ---

  function renderGrid() {
    photoGrid.innerHTML = '';
    photos.forEach((photo, idx) => {
      const item = document.createElement('div');
      item.className = 'photo-item';
      item.innerHTML = `
        <div class="photo-thumb-wrap">
          <img src="${photo.objectUrl}" alt="照片${idx + 1}" loading="lazy" />
          <button class="photo-remove" data-idx="${idx}" title="移除">✕</button>
        </div>
        <textarea
          class="photo-note"
          placeholder="备注（可选）"
          data-idx="${idx}"
          maxlength="80"
          rows="2"
        >${photo.note}</textarea>
      `;
      photoGrid.appendChild(item);
    });

    photoGrid.querySelectorAll('.photo-remove').forEach(btn => {
      btn.addEventListener('click', () => removePhoto(parseInt(btn.dataset.idx)));
    });
    photoGrid.querySelectorAll('.photo-note').forEach(ta => {
      ta.addEventListener('input', () => {
        photos[parseInt(ta.dataset.idx)].note = ta.value;
      });
    });
  }

  function removePhoto(idx) {
    URL.revokeObjectURL(photos[idx].objectUrl);
    photos.splice(idx, 1);
    if (photos.length === 0) {
      uploadCard.hidden = false;
      photosCard.hidden = true;
      controlsCard.hidden = true;
      fileInput.value = '';
    } else {
      renderGrid();
    }
  }

  // --- Style selector ---

  styleSelector.querySelectorAll('.style-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      styleSelector.querySelectorAll('.style-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      selectedStyle = btn.dataset.style;
    });
  });

  // --- Generate ---

  generateBtn.addEventListener('click', generate);
  regenerateBtn.addEventListener('click', generate);

  async function generate() {
    if (photos.length === 0) { showToast('请先上传照片'); return; }

    setLoading(true);
    resultCard.hidden = true;

    const fd = new FormData();
    photos.forEach(p => fd.append('photos', p.file));
    fd.append('notes', JSON.stringify(photos.map(p => p.note)));
    fd.append('style', selectedStyle);

    try {
      const resp = await fetch('/api/generate', { method: 'POST', body: fd });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '生成失败');
      showResult(data.narrative);
    } catch (err) {
      showToast(err.message || '网络异常，请重试');
    } finally {
      setLoading(false);
    }
  }

  function setLoading(on) {
    generateBtn.disabled = on;
    generateBtn.querySelector('.btn-text').hidden = on;
    generateBtn.querySelector('.btn-loading').hidden = !on;
  }

  function showResult(text) {
    resultText.textContent = text;
    resultStyleTag.textContent = styleNames[selectedStyle];
    resultCard.hidden = false;
    resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // --- Result actions ---

  copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(resultText.textContent)
      .then(() => showToast('已复制到剪贴板'))
      .catch(() => showToast('复制失败，请手动选取文字'));
  });

  resetBtn.addEventListener('click', () => {
    photos.forEach(p => URL.revokeObjectURL(p.objectUrl));
    photos = [];
    photoGrid.innerHTML = '';
    fileInput.value = '';
    addMoreInput.value = '';
    resultCard.hidden = true;
    controlsCard.hidden = true;
    photosCard.hidden = true;
    uploadCard.hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  // --- Toast ---

  let toastTimer;
  function showToast(msg) {
    let toast = document.querySelector('.toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.className = 'toast';
      document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2200);
  }
})();
