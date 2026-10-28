// A simple workflow: choose a station -> select many files -> upload and publish.
// Category maintenance is optional and stays in "Advanced".
const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));
const allowed = {
  png: 'image', jpg: 'image', jpeg: 'image', webp: 'image',
  mp3: 'audio', wav: 'audio', m4a: 'audio',
  mp4: 'video', webm: 'video'
};
const preferred = { image: 'gallery', audio: 'guide_audio', video: 'guide_video' };
const mediaNames = { image: '图片', audio: '音频', video: '视频' };
let categories = [], materials = [], queue = [];
let editingCode = null, replaceTarget = null, busy = false;
let selectedScenic = '', selectedStation = '';

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw Error(data.error || response.status);
  return data;
}

function notify(text, error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
}

async function safe(action) {
  try { await action(); }
  catch (error) { notify('操作失败：' + error.message, true); }
}

function setBusy(value) {
  busy = value;
  for (const control of document.querySelectorAll('button, select, input[type=file]')) {
    control.disabled = value;
  }
  $('uploadAndPublish').disabled = value || queue.length === 0;
}

function categoryName(code) {
  return categories.find(c => c.code === code)?.name || code;
}

function sizeLabel(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

function mediaType(file) {
  return allowed[file.name.split('.').pop().toLowerCase()] || null;
}

function optionsFor(type, selected) {
  return categories.filter(c => c.mediaType === type).map(c =>
    `<option value="${esc(c.code)}" ${selected === c.code ? 'selected' : ''}>${esc(c.name)}</option>`
  ).join('');
}

function chooseDefault(type) {
  const matches = categories.filter(c => c.mediaType === type);
  return matches.find(c => c.code === preferred[type])?.code || matches[0]?.code || null;
}

async function loadScenics() {
  const rows = await api('/api/scenics');
  const keep = $('scenic').value;
  $('scenic').innerHTML = rows.map(s =>
    `<option value="${esc(s.id)}">${esc(s.name)} · v${s.version}</option>`).join('');
  if (rows.some(s => s.id === keep)) $('scenic').value = keep;
  selectedScenic = $('scenic').value;
  await loadStations();
}

async function loadStations() {
  const old = $('station').value;
  const stations = await api('/api/stations?scenicId=' + encodeURIComponent($('scenic').value));
  $('station').innerHTML = stations.map(s =>
    `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');
  if (stations.some(s => s.id === old)) $('station').value = old;
  selectedStation = $('station').value;
  await loadMaterials();
  await loadManifest();
}

async function loadMaterials() {
  materials = await api('/api/materials?stationId=' + encodeURIComponent($('station').value));
  $('materialCount').textContent = materials.length + ' 个素材';
  if (!materials.length) {
    $('materials').innerHTML = '<p class="muted">这个站点还没有素材。直接在下方添加即可。</p>';
    return;
  }
  const groups = new Map();
  for (const item of materials) {
    if (!groups.has(item.categoryCode)) groups.set(item.categoryCode, []);
    groups.get(item.categoryCode).push(item);
  }
  const ordered = [...groups].sort((a, b) => {
    const rank = code => categories.find(c => c.code === code)?.position || 9999;
    return rank(a[0]) - rank(b[0]);
  });
  $('materials').innerHTML = ordered.map(([code, items]) =>
    `<div class="group"><h3>${esc(categoryName(code))} · ${items.length}</h3>${items.map(item =>
      `<div class="entry">
        <div><span class="entry-title">${esc(item.title)}</span>
          <div class="muted">${esc(mediaNames[item.mime.split('/')[0]] || item.mime)} · ${sizeLabel(item.size)}</div>
        </div>
        <div class="actions">
          <button class="secondary small" data-action="replace" data-id="${esc(item.id)}">替换</button>
          <button class="danger small" data-action="delete" data-id="${esc(item.id)}">删除</button>
        </div>
      </div>`).join('')}</div>`).join('');
}

async function loadManifest() {
  const path = '/api/scenics/' + encodeURIComponent($('scenic').value) + '/manifest';
  $('manifestLink').href = path;
  if ($('preview').closest('details').open) {
    $('preview').textContent = JSON.stringify(await api(path), null, 2);
  }
}

function renderQueue() {
  $('queue').hidden = queue.length === 0;
  $('queue').innerHTML = queue.map((entry, i) => `
    <div class="queue-row">
      <div>
        <input type="text" data-title="${i}" aria-label="素材名称" maxlength="120"
          value="${esc(entry.title)}" ${entry.uploaded || busy ? 'disabled' : ''}>
        <p class="filename">${esc(entry.file.name)} · ${mediaNames[entry.type]}
        ${entry.uploaded ? ' · 已上传，待发布' : ''}</p>
      </div>
      <select data-category="${i}" aria-label="素材分类" ${entry.uploaded || busy ? 'disabled' : ''}>
        ${optionsFor(entry.type, entry.categoryCode)}
      </select>
      <button class="secondary small" data-remove="${i}" ${entry.uploaded || busy ? 'disabled' : ''}>移除</button>
    </div>
  `).join('');
  $('uploadAndPublish').textContent = queue.length
    ? '上传 ' + queue.length + ' 个文件并发布'
    : '选择文件后上传并发布';
  $('uploadAndPublish').disabled = busy || queue.length === 0;
}

function addFiles(files) {
  const skipped = [];
  for (const file of files) {
    const type = mediaType(file);
    const code = type && chooseDefault(type);
    if (!code || file.size === 0 || file.size > 512 * 1024 * 1024) {
      skipped.push(file.name);
      continue;
    }
    queue.push({
      file, type, categoryCode: code,
      title: file.name.replace(/\.[^.]+$/, '').slice(0, 120),
      uploaded: false
    });
  }
  renderQueue();
  if (skipped.length) {
    notify('以下文件未加入：' + skipped.join('、') + '。请检查格式、大小（不超过 512 MB）及分类设置。', true);
  } else if (queue.length) {
    notify('分类已自动匹配，可直接上传；需要时也能逐个调整。');
  }
}

async function uploadMaterial(file, stationId, categoryCode, title) {
  const query = new URLSearchParams({
    stationId, categoryCode, title, filename: file.name
  });
  return api('/api/materials?' + query, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: file
  });
}

async function publish(scenicId) {
  await api('/api/scenics/' + encodeURIComponent(scenicId) + '/publish', { method: 'POST' });
}

async function runBusy(action) {
  if (busy) return;
  setBusy(true);
  try { await action(); }
  finally { setBusy(false); renderQueue(); }
}

$('scenic').onchange = () => safe(async () => {
  if (queue.length && !confirm('切换景区会清空待上传列表；已上传的草稿需要之后发布。确定切换吗？')) {
    $('scenic').value = selectedScenic;
    return;
  }
  queue = [];
  renderQueue();
  selectedScenic = $('scenic').value;
  await loadStations();
});
$('station').onchange = () => safe(async () => {
  if (queue.length && !confirm('切换站点会清空待上传列表；已上传的草稿需要之后发布。确定切换吗？')) {
    $('station').value = selectedStation;
    return;
  }
  queue = [];
  renderQueue();
  selectedStation = $('station').value;
  await loadMaterials();
});

$('files').onchange = event => {
  addFiles(Array.from(event.target.files));
  event.target.value = '';
};
$('dropzone').ondragover = event => {
  event.preventDefault();
  $('dropzone').classList.add('drag');
};
$('dropzone').ondragleave = () => $('dropzone').classList.remove('drag');
$('dropzone').ondrop = event => {
  event.preventDefault();
  $('dropzone').classList.remove('drag');
  if (!busy) addFiles(Array.from(event.dataTransfer.files));
};
$('queue').oninput = event => {
  const index = event.target.dataset.title;
  if (index !== undefined) queue[Number(index)].title = event.target.value;
};
$('queue').onchange = event => {
  const index = event.target.dataset.category;
  if (index !== undefined) queue[Number(index)].categoryCode = event.target.value;
};
$('queue').onclick = event => {
  const index = event.target.dataset.remove;
  if (!busy && index !== undefined && !queue[Number(index)].uploaded) {
    queue.splice(Number(index), 1);
    renderQueue();
  }
};
$('uploadAndPublish').onclick = () => safe(() => runBusy(async () => {
  if (!queue.length) return;
  if (!queue.every(item => item.title.trim().length && item.categoryCode &&
      categories.some(c => c.code === item.categoryCode && c.mediaType === item.type))) {
    throw Error('请检查文件名称和分类');
  }
  const stationId = $('station').value, scenicId = $('scenic').value;
  let completed = queue.filter(item => item.uploaded).length;
  for (const item of queue) {
    if (item.uploaded) continue;
    notify('上传中：' + (completed + 1) + ' / ' + queue.length + ' · ' + item.file.name);
    await uploadMaterial(item.file, stationId, item.categoryCode, item.title.trim());
    item.uploaded = true;
    completed++;
    renderQueue();
  }
  notify('上传完成，正在发布景区版本…');
  await publish(scenicId);
  const total = queue.length;
  queue = [];
  renderQueue();
  await loadScenics();
  notify('已上传并发布 ' + total + ' 个文件，车机下次联网即可同步。');
}));

$('materials').onclick = event => {
  const button = event.target.closest('button[data-action]');
  if (!button || busy) return;
  const item = materials.find(m => m.id === button.dataset.id);
  if (!item) return;
  if (queue.length) return notify('请先完成当前上传队列，再操作已有素材。', true);
  if (button.dataset.action === 'replace') {
    replaceTarget = item;
    const type = item.mime.split('/')[0];
    $('replaceFile').accept = Object.entries(allowed)
      .filter(([extension, media]) => media === type)
      .map(([extension]) => '.' + extension).join(',');
    $('replaceFile').click();
  } else if (confirm('删除「' + item.title + '」并立即发布当前景区？')) {
    safe(() => runBusy(async () => {
      await api('/api/materials/' + encodeURIComponent(item.id), { method: 'DELETE' });
      await publish($('scenic').value);
      await loadScenics();
      notify('已删除并发布，车机会在更新后移除该素材引用。');
    }));
  }
};

$('replaceFile').onchange = event => {
  const file = event.target.files[0], item = replaceTarget;
  event.target.value = '';
  replaceTarget = null;
  if (!file || !item) return;
  if (mediaType(file) !== item.mime.split('/')[0] || !file.size || file.size > 512 * 1024 * 1024) {
    return notify('替换文件必须与原素材的媒体类型一致，且不超过 512 MB。', true);
  }
  safe(() => runBusy(async () => {
    notify('正在上传替换文件…');
    await uploadMaterial(file, $('station').value, item.categoryCode, item.title);
    await api('/api/materials/' + encodeURIComponent(item.id), { method: 'DELETE' });
    await publish($('scenic').value);
    await loadScenics();
    notify('已替换并发布。');
  }));
};

// Rare maintenance operations remain available without cluttering the main workflow.
async function loadCategories() {
  categories = await api('/api/categories');
  $('categoryRows').innerHTML = categories.map(c => `
    <div class="entry">
      <div><strong>${esc(c.name)}</strong>
        <span class="muted">${esc(c.code)} · ${mediaNames[c.mediaType]} · 排序 ${c.position}</span></div>
      <div class="actions">
        <button class="secondary small" data-action="edit" data-code="${esc(c.code)}">编辑</button>
        <button class="danger small" data-action="delete" data-code="${esc(c.code)}">删除</button>
      </div>
    </div>`).join('');
  renderQueue();
}

function resetCategoryEditor() {
  editingCode = null;
  $('catCode').value = '';
  $('catCode').disabled = false;
  $('catName').value = '';
  $('catType').value = 'image';
  $('catPosition').value = '';
  $('saveCategory').textContent = '保存分类';
  $('cancelCategory').hidden = true;
}

$('categoryRows').onclick = event => {
  const button = event.target.closest('button[data-action]');
  if (!button || busy) return;
  const category = categories.find(c => c.code === button.dataset.code);
  if (!category) return;
  if (button.dataset.action === 'edit') {
    editingCode = category.code;
    $('catCode').value = category.code;
    $('catCode').disabled = true;
    $('catName').value = category.name;
    $('catType').value = category.mediaType;
    $('catPosition').value = category.position;
    $('saveCategory').textContent = '保存修改';
    $('cancelCategory').hidden = false;
  } else if (confirm('删除分类「' + category.name + '」？已被素材使用的分类不能删除。')) {
    safe(() => runBusy(async () => {
      await api('/api/categories/' + encodeURIComponent(category.code), { method: 'DELETE' });
      resetCategoryEditor();
      await loadCategories();
      notify('分类已删除。如有历史版本涉及此分类，旧版本仍保留。');
    }));
  }
};
$('cancelCategory').onclick = resetCategoryEditor;
$('saveCategory').onclick = () => safe(() => runBusy(async () => {
  const data = { name: $('catName').value.trim(), mediaType: $('catType').value };
  if ($('catPosition').value) data.position = Number($('catPosition').value);
  if (!editingCode) data.code = $('catCode').value.trim();
  const path = editingCode
    ? '/api/categories/' + encodeURIComponent(editingCode)
    : '/api/categories';
  await api(path, {
    method: editingCode ? 'PATCH' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  resetCategoryEditor();
  await loadCategories();
  await loadMaterials();
  notify('分类已保存。涉及已有素材的变更需重新发布相关景区。');
}));

$('publish').onclick = () => safe(() => runBusy(async () => {
  if (queue.length) throw Error('请先上传并发布当前待上传文件。');
  await publish($('scenic').value);
  await loadScenics();
  notify('当前景区已发布。');
}));
$('preview').closest('details').ontoggle = () => {
  if ($('preview').closest('details').open) safe(loadManifest);
};

safe(async () => {
  await loadCategories();
  await loadScenics();
});
