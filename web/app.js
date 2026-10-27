// The admin is intentionally small: no framework, build step, or extra dependencies.
const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));
let categories = [];
let editingCode = null;

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw Error(body.error || response.status);
  return body;
}

async function safe(action) {
  try {
    $('message').textContent = '';
    await action();
  } catch (error) {
    $('message').textContent = '错误：' + error.message;
  }
}

async function loadScenics() {
  const selected = $('scenic').value;
  const rows = await api('/api/scenics');
  $('scenic').innerHTML = rows.map(s =>
    `<option value="${esc(s.id)}">${esc(s.name)} · v${s.version}</option>`).join('');
  if (rows.some(s => s.id === selected)) $('scenic').value = selected;
  await loadStations();
}

async function loadStations() {
  const selected = $('station').value;
  const rows = await api('/api/stations?scenicId=' + encodeURIComponent($('scenic').value));
  $('station').innerHTML = rows.map(s =>
    `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');
  if (rows.some(s => s.id === selected)) $('station').value = selected;
  await loadMaterials();
  await loadManifest();
}

async function loadMaterials() {
  const rows = await api('/api/materials?stationId=' + encodeURIComponent($('station').value));
  $('materials').innerHTML = rows.length ? rows.map(item =>
    `<div class="item"><div><b>${esc(item.title)}</b><br>
    <span class="muted">${esc(item.categoryCode)} · ${esc(item.mime)} · ${(item.size / 1024).toFixed(1)} KiB</span>
    </div><button class="small" data-id="${esc(item.id)}">删除</button></div>`).join('')
    : '<p class="muted">该站点尚无素材</p>';
}

async function loadManifest() {
  const path = '/api/scenics/' + encodeURIComponent($('scenic').value) + '/manifest';
  $('manifestLink').href = path;
  $('preview').textContent = JSON.stringify(await api(path), null, 2);
}

async function loadCategories() {
  const selected = $('category').value;
  categories = await api('/api/categories');
  $('category').innerHTML = categories.map(c =>
    `<option value="${esc(c.code)}">${esc(c.name)}（${esc(c.mediaType)}）</option>`).join('');
  if (categories.some(c => c.code === selected)) $('category').value = selected;
  $('categoryRows').innerHTML = categories.map(c =>
    `<div class="item"><div><b>${esc(c.name)}</b>
    <span class="muted">${esc(c.code)} · ${esc(c.mediaType)} · 排序 ${c.position}</span></div>
    <div class="actions"><button class="small" data-action="edit" data-code="${esc(c.code)}">编辑</button>
    <button class="small" data-action="delete" data-code="${esc(c.code)}">删除</button></div></div>`).join('');
  updateFileType();
}

function updateFileType() {
  const category = categories.find(c => c.code === $('category').value);
  $('file').accept = category ? category.mediaType + '/*' : 'image/*,audio/*,video/*';
  $('typeHelp').textContent = category
    ? '当前分类只允许上传' + ({ image: '图片', audio: '音频', video: '视频' }[category.mediaType]) + '文件'
    : '';
}

function resetCategoryEditor() {
  editingCode = null;
  $('catCode').disabled = false;
  $('catCode').value = '';
  $('catName').value = '';
  $('catType').value = 'image';
  $('catPosition').value = '';
  $('saveCategory').textContent = '新增分类';
  $('cancelCategory').hidden = true;
}

$('scenic').onchange = () => safe(loadStations);
$('station').onchange = () => safe(loadMaterials);
$('category').onchange = updateFileType;
$('cancelCategory').onclick = resetCategoryEditor;

$('categoryRows').onclick = event => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
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
  } else if (confirm('删除分类「' + category.name + '」？正在使用的分类不能删除。')) {
    safe(async () => {
      await api('/api/categories/' + encodeURIComponent(category.code), { method: 'DELETE' });
      resetCategoryEditor();
      await loadCategories();
      $('message').textContent = '分类已删除';
    });
  }
};

$('saveCategory').onclick = () => safe(async () => {
  const data = { name: $('catName').value.trim(), mediaType: $('catType').value };
  if ($('catPosition').value) data.position = Number($('catPosition').value);
  const path = editingCode ? '/api/categories/' + encodeURIComponent(editingCode) : '/api/categories';
  if (!editingCode) data.code = $('catCode').value.trim();
  await api(path, {
    method: editingCode ? 'PATCH' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  resetCategoryEditor();
  await loadCategories();
  $('message').textContent = '分类已保存；若站点正在使用此分类，请重新发布对应景区';
});

$('materials').onclick = event => {
  const id = event.target.dataset.id;
  if (id && confirm('删除该素材引用？文件不会立即删除，已发布版本保持不变。')) {
    safe(async () => {
      await api('/api/materials/' + encodeURIComponent(id), { method: 'DELETE' });
      await loadMaterials();
    });
  }
};

$('upload').onclick = () => safe(async () => {
  const file = $('file').files[0];
  const title = $('title').value.trim();
  if (!file || !title) throw Error('请选择文件并填写标题');
  const query = new URLSearchParams({
    stationId: $('station').value, categoryCode: $('category').value,
    title, filename: file.name
  });
  $('upload').disabled = true;
  try {
    await api('/api/materials?' + query, {
      method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file
    });
    $('file').value = '';
    await loadMaterials();
    $('message').textContent = '上传成功，请发布后同步到车机';
  } finally {
    $('upload').disabled = false;
  }
});

$('publish').onclick = () => safe(async () => {
  await api('/api/scenics/' + encodeURIComponent($('scenic').value) + '/publish', { method: 'POST' });
  await loadScenics();
  $('message').textContent = '已发布新版本';
});

safe(async () => {
  await loadCategories();
  await loadScenics();
});
