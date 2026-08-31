/**
 * Google Drive Multi Mail - Dashboard JavaScript
 */

const API = '';  // Same origin

// ════════════════ Tab Navigation ════════════════

function switchTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));

    // Show selected tab
    const tab = document.getElementById(`tab-${tabName}`);
    if (tab) tab.classList.add('active');

    const btn = document.querySelector(`[data-tab="${tabName}"]`);
    if (btn) btn.classList.add('active');

    // Load data for the tab
    switch(tabName) {
        case 'dashboard': loadDashboard(); break;
        case 'files': loadFiles('/'); updateBreadcrumb('/'); loadFolderTree(); break;
        case 'accounts': loadAccounts(); break;
        case 'drives': loadDrives(); break;
    }
}

// ════════════════ Utilities ════════════════

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

function getFileIcon(filename, isSplit) {
    if (isSplit) return '✂️';
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        'pdf': '📕', 'doc': '📘', 'docx': '📘', 'xls': '📗', 'xlsx': '📗',
        'ppt': '📙', 'pptx': '📙', 'jpg': '🖼️', 'jpeg': '🖼️', 'png': '🖼️',
        'gif': '🖼️', 'mp4': '🎬', 'mp3': '🎵', 'zip': '📦', 'rar': '📦',
        'py': '🐍', 'js': '⚡', 'html': '🌐', 'css': '🎨', 'md': '📝',
        'txt': '📝', 'json': '📋', 'csv': '📊',
    };
    return icons[ext] || '📄';
}

// ════════════════ Dashboard ════════════════

async function loadDashboard() {
    try {
        // Load storage summary
        const summaryRes = await fetch(`${API}/api/drives/summary`);
        const summary = await summaryRes.json();

        document.getElementById('stat-total').textContent = formatBytes(summary.total_bytes);
        document.getElementById('stat-used').textContent = formatBytes(summary.used_bytes);
        document.getElementById('stat-available').textContent = formatBytes(summary.available_bytes);

        const pct = summary.total_bytes > 0
            ? ((summary.used_bytes / summary.total_bytes) * 100).toFixed(1)
            : 0;
        document.getElementById('storage-fill').style.width = `${pct}%`;
        document.getElementById('storage-label').textContent = `${pct}%`;

        // Load file count
        const filesRes = await fetch(`${API}/api/files/all`);
        const filesData = await filesRes.json();
        document.getElementById('stat-files').textContent = filesData.files.length;

        // Load drive list
        const drivesRes = await fetch(`${API}/api/drives`);
        const drivesData = await drivesRes.json();
        const driveContainer = document.getElementById('drive-list-dashboard');
        driveContainer.innerHTML = drivesData.drives.map(d => `
            <div class="drive-card">
                <div class="drive-email">📧 ${d.email}</div>
                <div class="drive-quota">
                    <span>💾 ${formatBytes(d.total_bytes)}</span>
                    <span>📊 ${formatBytes(d.used_bytes)} ใช้แล้ว</span>
                    <span>✅ ${formatBytes(d.available_bytes)} ว่าง</span>
                </div>
            </div>
        `).join('') || '<div class="empty-state"><div class="empty-icon">💾</div><p>ยังไม่มี Drive ที่เชื่อมต่อ</p></div>';

        // Load sync status
        loadSyncStatus();

    } catch (err) {
        console.error('Dashboard load error:', err);
    }
}

async function loadSyncStatus() {
    try {
        const res = await fetch(`${API}/api/drives/sync/status`);
        const s = await res.json();

        const dot = document.getElementById('sync-status-dot');
        const text = document.getElementById('sync-status-text');

        if (s.is_running) {
            dot.className = 'status-dot status-pending';
            text.textContent = 'กำลังซิงค์...';
        } else if (s.last_sync_result === 'ok') {
            dot.className = 'status-dot status-active';
            text.textContent = 'ซิงค์สำเร็จ';
        } else if (s.last_sync_result === 'no_accounts') {
            dot.className = 'status-dot status-pending';
            text.textContent = 'ยังไม่มีบัญชีที่เชื่อมต่อ Drive';
        } else if (s.last_sync_result === 'error') {
            dot.className = 'status-dot status-inactive';
            text.textContent = `ซิงค์ล้มเหลว (${s.consecutive_errors} ครั้งติดต่อกัน)`;
        } else {
            dot.className = 'status-dot status-pending';
            text.textContent = 'รอการซิงค์ครั้งแรก...';
        }

        document.getElementById('sync-count').textContent = s.total_syncs;
        document.getElementById('sync-last').textContent = s.last_sync_at
            ? new Date(s.last_sync_at).toLocaleString('th-TH')
            : 'ยังไม่เคยซิงค์';
        document.getElementById('sync-next').textContent = s.next_sync_at
            ? new Date(s.next_sync_at).toLocaleString('th-TH')
            : '--';
        document.getElementById('sync-duration').textContent = s.last_sync_duration_seconds != null
            ? `${s.last_sync_duration_seconds}s`
            : '--';

    } catch (err) {
        console.error('Sync status load error:', err);
    }
}

async function manualSync() {
    showToast('กำลังซิงค์ Drive...');
    try {
        const res = await fetch(`${API}/api/drives/sync`, { method: 'POST' });
        const data = await res.json();

        if (data.result?.status === 'ok' || data.result?.status === 'no_accounts') {
            showToast('ซิงค์สำเร็จ');
        } else {
            showToast('ซิงค์บางส่วนล้มเหลว', 'error');
        }

        // Refresh dashboard data
        loadDashboard();
    } catch (err) {
        showToast('ซิงค์ล้มเหลว', 'error');
    }
}

// ════════════════ Files + Folder Tree ════════════════

let currentFolder = '/';
let currentPreviewFileId = null;
let folderTreeExpanded = new Set(['/']); // track expanded nodes

// ─── Folder Tree ───

async function loadFolderTree() {
    const container = document.getElementById('folder-tree');
    if (!container) return;
    try {
        const res = await fetch(`${API}/api/folders/tree`);
        const data = await res.json();
        container.innerHTML = renderFolderTree(data.tree['/'], '/', 0);
        highlightActiveFolder();
    } catch (err) {
        container.innerHTML = '<div class="loading">เกิดข้อผิดพลาด</div>';
    }
}

function renderFolderTree(node, path, depth) {
    const children = node.children || {};
    const childPaths = Object.keys(children).sort();
    const hasChildren = childPaths.length > 0;
    const isExpanded = folderTreeExpanded.has(path);
    const isActive = path === currentFolder;
    const indent = depth * 16;
    const displayName = path === '/' ? '🏠 Root' : node.name;
    const totalCount = (node.file_count || 0) + childPaths.reduce((sum, cp) => sum + (children[cp]?.file_count || 0), 0);

    let html = `<div class="tree-item ${isActive ? 'active' : ''}" style="padding-left:${indent + 8}px" onclick="navigateFolder('${escapePath(path)}')" title="${path}">`;

    if (hasChildren) {
        html += `<span class="tree-toggle ${isExpanded ? 'open' : ''}" onclick="event.stopPropagation();toggleFolder('${escapePath(path)}')">▶</span>`;
    } else {
        html += `<span class="tree-toggle" style="visibility:hidden">▶</span>`;
    }

    html += `<span class="tree-item-icon">${hasChildren && isExpanded ? '📂' : '📁'}</span>`;
    html += `<span class="tree-item-name">${displayName}</span>`;

    if (totalCount > 0) {
        html += `<span class="tree-item-count">${totalCount}</span>`;
    }

    html += `</div>`;

    if (hasChildren) {
        html += `<div class="tree-children ${isExpanded ? 'open' : ''}">`;
        for (const cp of childPaths) {
            html += renderFolderTree(children[cp], cp, depth + 1);
        }
        html += `</div>`;
    }

    return html;
}

function escapePath(p) {
    return p.replace(/'/g, "\\'").replace(/\/\//g, '/');
}

function toggleFolder(path) {
    if (folderTreeExpanded.has(path)) {
        folderTreeExpanded.delete(path);
    } else {
        folderTreeExpanded.add(path);
    }
    loadFolderTree();
}

function navigateFolder(path) {
    currentFolder = path;
    closePreview();
    loadFiles(path);
    updateBreadcrumb(path);
    highlightActiveFolder();
}

function highlightActiveFolder() {
    document.querySelectorAll('.tree-item').forEach(el => {
        el.classList.remove('active');
    });
    // Find and highlight the active item
    document.querySelectorAll('.tree-item').forEach(el => {
        if (el.getAttribute('title') === currentFolder) {
            el.classList.add('active');
        }
    });
}

// ─── Breadcrumb ───

function updateBreadcrumb(path) {
    const bar = document.getElementById('breadcrumb-bar');
    if (!bar) return;

    const parts = path.split('/').filter(Boolean);
    let html = `<span class="breadcrumb-item ${parts.length === 0 ? 'current' : ''}" onclick="navigateFolder('/')">🏠 root</span>`;

    let accumulated = '';
    for (let i = 0; i < parts.length; i++) {
        accumulated += '/' + parts[i];
        const isCurrent = i === parts.length - 1;
        html += `<span class="breadcrumb-sep">/</span>`;
        html += `<span class="breadcrumb-item ${isCurrent ? 'current' : ''}" onclick="navigateFolder('${escapePath(accumulated)}')">${parts[i]}</span>`;
    }

    bar.innerHTML = html;
}

// ─── Load Files in Folder ───

async function loadFiles(folder = '/') {
    currentFolder = folder;
    const container = document.getElementById('file-list');
    if (!container) return;
    container.innerHTML = '<div class="loading">กำลังโหลด...</div>';

    try {
        const res = await fetch(`${API}/api/files?folder=${encodeURIComponent(folder)}`);
        const data = await res.json();

        if (data.files.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📁</div>
                    <p>โฟลเดอร์นี้ว่างเปล่า</p>
                    <p><a href="#" onclick="switchTab('upload')" style="color:var(--accent)">⬆️ อัพโหลดไฟล์</a></p>
                </div>`;
            return;
        }

        container.innerHTML = data.files.map(f => `
            <div class="file-item" onclick="previewFile(${f.file_id}, '${escapePath(f.filename)}', '${f.mime_type || ''}')" data-file-id="${f.file_id}">
                <div class="file-icon">${getFileIcon(f.filename, f.is_split)}</div>
                <div class="file-info">
                    <div class="file-name">
                        ${f.filename}
                        ${f.is_split ? '<span class="split-badge">✂️ แบ่ง ' + f.num_chunks + ' ส่วน</span>' : ''}
                    </div>
                    <div class="file-meta">
                        ${formatBytes(f.size)} • ${f.tags.map(t => `<span class="tag">${t}</span>`).join(' ')}
                        • ${new Date(f.created_at).toLocaleDateString('th-TH')}
                    </div>
                </div>
                <div class="file-actions">
                    <button class="btn btn-sm btn-primary" onclick="event.stopPropagation();downloadFile(${f.file_id})" title="ดาวน์โหลด">⬇️</button>
                    <button class="btn btn-sm btn-danger" onclick="event.stopPropagation();deleteFile(${f.file_id})" title="ลบ">🗑️</button>
                </div>
            </div>
        `).join('');

    } catch (err) {
        container.innerHTML = '<div class="empty-state"><p>เกิดข้อผิดพลาดในการโหลด</p></div>';
    }
}

// ─── File Preview ───

async function previewFile(fileId, filename, mimeType) {
    const panel = document.getElementById('preview-panel');
    const body = document.getElementById('preview-body');
    const title = document.getElementById('preview-filename');
    if (!panel || !body) return;

    currentPreviewFileId = fileId;
    panel.style.display = 'flex';
    title.textContent = filename;

    // Highlight selected file
    document.querySelectorAll('.file-item').forEach(el => el.classList.remove('selected'));
    const item = document.querySelector(`.file-item[data-file-id="${fileId}"]`);
    if (item) item.classList.add('selected');

    body.innerHTML = '<div class="loading">กำลังโหลด preview...</div>';

    try {
        const res = await fetch(`${API}/api/files/${fileId}/preview`);
        const data = await res.json();

        if (!data.previewable) {
            body.innerHTML = `
                <div class="preview-not-available">
                    <div class="icon">${getFileIcon(filename, false)}</div>
                    <p>${data.message || 'ไม่สามารถ preview ได้'}</p>
                    <button class="btn btn-primary" style="margin-top:1rem" onclick="downloadFile(${fileId})">⬇️ ดาวน์โหลด</button>
                </div>`;
            return;
        }

        // Meta info
        let html = `<div class="preview-meta">
            <div class="preview-meta-row"><span>ไฟล์:</span><span>${data.filename}</span></div>
            <div class="preview-meta-row"><span>ขนาด:</span><span>${formatBytes(data.size)}</span></div>
            <div class="preview-meta-row"><span>ประเภท:</span><span>${data.mime_type}</span></div>
            <div class="preview-meta-row"><span>ID:</span><span>${fileId}</span></div>
        </div>`;

        if (data.type === 'image') {
            html += `<img class="preview-image" src="${data.data}" alt="${data.filename}">`;
        } else if (data.type === 'pdf') {
            html += `<iframe class="preview-pdf" src="${data.data}" title="${data.filename}"></iframe>`;
        } else if (data.type === 'text') {
            const escaped = data.content
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
            const lines = escaped.split('\n');
            const numbered = lines.map((l, i) => `<span class="line-num">${String(i + 1).padStart(4)}</span> ${l}`).join('\n');
            html += `<div class="preview-code">${numbered}</div>`;
        }

        html += `<div style="margin-top:1rem;display:flex;gap:0.5rem">
            <button class="btn btn-primary" onclick="downloadFile(${fileId})">⬇️ ดาวน์โหลด</button>
            <button class="btn btn-sm" onclick="showFileDetail(${fileId})">📋 รายละเอียด</button>
        </div>`;

        body.innerHTML = html;

    } catch (err) {
        body.innerHTML = `<div class="preview-not-available"><div class="icon">⚠️</div><p>เกิดข้อผิดพลาดในการโหลด preview</p></div>`;
    }
}

function closePreview() {
    const panel = document.getElementById('preview-panel');
    if (panel) panel.style.display = 'none';
    currentPreviewFileId = null;
    document.querySelectorAll('.file-item').forEach(el => el.classList.remove('selected'));
}

// ─── Folder Dialog ───

function showNewFolderDialog() {
    const dialog = document.getElementById('folder-dialog');
    const parentInput = document.getElementById('new-folder-parent');
    if (dialog && parentInput) {
        parentInput.value = currentFolder;
        document.getElementById('new-folder-name').value = '';
        dialog.style.display = 'flex';
        document.getElementById('new-folder-name').focus();
    }
}

function closeFolderDialog() {
    const dialog = document.getElementById('folder-dialog');
    if (dialog) dialog.style.display = 'none';
}

async function createFolder(e) {
    e.preventDefault();
    const name = document.getElementById('new-folder-name').value.trim();
    const parent = document.getElementById('new-folder-parent').value;

    if (!name) return;

    try {
        const formData = new FormData();
        formData.append('name', name);
        formData.append('parent_path', parent);

        const res = await fetch(`${API}/api/folders`, { method: 'POST', body: formData });
        const data = await res.json();

        if (res.ok) {
            showToast(`สร้างโฟลเดอร์ "${name}" สำเร็จ`);
            closeFolderDialog();
            // Expand parent and refresh tree
            folderTreeExpanded.add(parent);
            loadFolderTree();
        } else {
            showToast(data.detail || 'เกิดข้อผิดพลาด', 'error');
        }
    } catch (err) {
        showToast('เกิดข้อผิดพลาด', 'error');
    }
}

async function showFileDetail(fileId) {
    try {
        const res = await fetch(`${API}/api/files/${fileId}`);
        const f = await res.json();

        const modal = document.getElementById('file-modal');
        const body = document.getElementById('modal-body');

        body.innerHTML = `
            <h3>${getFileIcon(f.filename, f.is_split)} ${f.filename}</h3>
            <p><strong>ขนาด:</strong> ${formatBytes(f.size)}</p>
            <p><strong>ประเภท:</strong> ${f.mime_type || 'ไม่ทราบ'}</p>
            <p><strong>โฟลเดอร์:</strong> ${f.folder}</p>
            <p><strong>MD5:</strong> <code>${f.md5_hash || 'N/A'}</code></p>
            <p><strong>สร้างเมื่อ:</strong> ${new Date(f.created_at).toLocaleString('th-TH')}</p>
            ${f.description ? `<p><strong>คำอธิบาย:</strong> ${f.description}</p>` : ''}
            ${f.tags.length ? `<p><strong>แท็ก:</strong> ${f.tags.map(t => `<span class="tag">${t}</span>`).join(' ')}</p>` : ''}
            ${f.is_split ? `
                <h3>📍 ตำแหน่งไฟล์ (${f.num_chunks} ส่วน)</h3>
                ${f.locations.chunks.map(c => `
                    <div class="drive-card">
                        <div class="drive-email">ส่วนที่ ${c.chunk_index + 1}</div>
                        <div class="drive-quota">
                            <span>📧 ${c.drive_account}</span>
                            <span>💾 ${formatBytes(c.chunk_size)}</span>
                            <span>✅ ${c.status}</span>
                        </div>
                    </div>
                `).join('')}
            ` : `
                <h3>📍 ตำแหน่งไฟล์</h3>
                ${f.locations.chunks.map(c => `
                    <div class="drive-card">
                        <div class="drive-email">📧 ${c.drive_account}</div>
                        <div class="drive-quota">
                            <span>Google Drive ID: <code>${c.google_drive_file_id || 'N/A'}</code></span>
                            <span>✅ ${c.status}</span>
                        </div>
                    </div>
                `).join('')}
            `}
            <div style="margin-top:1.5rem;display:flex;gap:0.5rem">
                <button class="btn btn-primary" onclick="downloadFile(${f.file_id})">⬇️ ดาวน์โหลด</button>
                <button class="btn btn-danger" onclick="deleteFile(${f.file_id});closeModal()">🗑️ ลบไฟล์</button>
            </div>
        `;

        modal.style.display = 'flex';

    } catch (err) {
        showToast('เกิดข้อผิดพลาด', 'error');
    }
}

function closeModal() {
    document.getElementById('file-modal').style.display = 'none';
}

async function downloadFile(fileId) {
    try {
        showToast('กำลังดาวน์โหลด...');

        // Fetch file as blob
        const res = await fetch(`${API}/api/files/${fileId}/download`);
        if (!res.ok) {
            const err = await res.json();
            showToast(err.detail || 'ดาวน์โหลดล้มเหลว', 'error');
            return;
        }

        // Get filename from Content-Disposition header
        const disposition = res.headers.get('Content-Disposition');
        let filename = 'download';
        if (disposition) {
            const match = disposition.match(/filename="?(.+?)"?$/);
            if (match) filename = decodeURIComponent(match[1]);
        }

        // Create blob and trigger download
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();

        showToast(`ดาวน์โหลดสำเร็จ: ${filename}`);
    } catch (err) {
        showToast('ดาวน์โหลดล้มเหลว: ' + err.message, 'error');
    }
}

async function deleteFile(fileId) {
    if (!confirm('ต้องการลบไฟล์นี้จริงหรือไม่?')) return;
    try {
        const res = await fetch(`${API}/api/files/${fileId}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'error') {
            showToast(data.message, 'error');
        } else {
            showToast('ลบไฟล์สำเร็จ');
            loadFiles('/');
        }
    } catch (err) {
        showToast('ลบล้มเหลว', 'error');
    }
}

// ════════════════ Upload (WebSocket) ════════════════

const WS_MAX_CONCURRENT = 3;   // max parallel WebSocket uploads
const CHUNK_SIZE = 4 * 1024 * 1024;  // 4MB per binary frame

let wsConnections = [];         // active WebSocket connections
let activeUploads = new Map();  // upload_id -> state
let uploadQueue = [];           // files waiting for a slot
let wsConnecting = false;

// ─── Drag & Drop ───
const uploadArea = document.getElementById('upload-area');
const fileInput = document.getElementById('file-input');

if (uploadArea) {
    uploadArea.addEventListener('dragover', e => {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.add('drag-over');
    });
    uploadArea.addEventListener('dragleave', e => {
        e.preventDefault();
        uploadArea.classList.remove('drag-over');
    });
    uploadArea.addEventListener('drop', e => {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.remove('drag-over');
        enqueueFiles(e.dataTransfer.files);
    });
}
if (fileInput) {
    fileInput.addEventListener('change', () => {
        enqueueFiles(fileInput.files);
        fileInput.value = '';  // allow re-selecting same files
    });
}

// ─── Queue Management ───
function enqueueFiles(fileList) {
    for (const file of fileList) {
        uploadQueue.push(file);
    }
    processUploadQueue();
}

function processUploadQueue() {
    while (uploadQueue.length > 0 && wsConnections.length < WS_MAX_CONCURRENT) {
        const file = uploadQueue.shift();
        startWebSocketUpload(file);
    }
    updateOverallProgress();
}

// ─── WebSocket Upload ───
function startWebSocketUpload(file) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/upload`;
    const ws = new WebSocket(wsUrl);

    const uploadId = crypto.randomUUID().slice(0, 12);
    const desc = document.getElementById('upload-description')?.value || '';
    const tags = document.getElementById('upload-tags')?.value || '';
    const folder = document.getElementById('upload-folder')?.value || '/';

    const state = {
        id: uploadId,
        ws: ws,
        file: file,
        filename: file.name,
        fileSize: file.size,
        phase: 'connecting',
        progress: 0,
        speed: 0,
        eta: null,
        fileId: null,
        error: null,
        startTime: Date.now(),
    };

    activeUploads.set(uploadId, state);
    wsConnections.push(ws);
    createUploadCard(state);

    ws.onopen = () => {
        state.phase = 'handshake';
        // Send file metadata
        ws.send(JSON.stringify({
            type: 'start',
            filename: file.name,
            file_size: file.size,
            mime_type: file.type || 'application/octet-stream',
            description: desc,
            tags: tags,
            folder_path: folder,
        }));
    };

    ws.onmessage = (evt) => {
        if (typeof evt.data !== 'string') return;
        const msg = JSON.parse(evt.data);
        handleUploadMessage(uploadId, msg);
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        state.phase = 'error';
        state.error = 'Connection error';
        updateUploadCard(state);
        cleanupWs(ws);
    };

    ws.onclose = () => {
        if (state.phase !== 'complete' && state.phase !== 'error' && state.phase !== 'cancelled') {
            state.phase = 'error';
            state.error = 'Connection closed unexpectedly';
            updateUploadCard(state);
        }
        cleanupWs(ws);
    };

    // Start reading and sending the file once server acknowledges
    // (handled in handleUploadMessage when type=started)
}

function handleUploadMessage(uploadId, msg) {
    const state = activeUploads.get(uploadId);
    if (!state) return;

    switch (msg.type) {
        case 'started':
            state.phase = 'uploading';
            state.totalChunks = msg.total_chunks || 1;
            state.chunkSize = msg.chunk_size || state.fileSize;
            updateUploadCard(state);
            // Begin streaming file data
            streamFile(uploadId);
            break;

        case 'progress':
            state.phase = msg.phase || state.phase;
            state.progress = msg.progress || 0;
            state.speed = msg.speed_bps || 0;
            state.eta = msg.eta_seconds;
            updateUploadCard(state);
            updateOverallProgress();
            break;

        case 'complete':
            state.phase = 'complete';
            state.progress = 100;
            state.fileId = msg.file_id;
            state.isSplit = msg.is_split;
            state.numChunks = msg.num_chunks_uploaded;
            state.chunks = msg.chunks;
            state.elapsed = msg.elapsed;
            updateUploadCard(state);
            updateOverallProgress();
            loadFiles('/');
            break;

        case 'error':
            state.phase = 'error';
            state.error = msg.error || 'Unknown error';
            updateUploadCard(state);
            updateOverallProgress();
            break;

        case 'cancelled':
            state.phase = 'cancelled';
            updateUploadCard(state);
            updateOverallProgress();
            break;
    }
}

async function streamFile(uploadId) {
    const state = activeUploads.get(uploadId);
    if (!state || !state.ws || state.ws.readyState !== WebSocket.OPEN) return;

    try {
        const file = state.file;
        const chunkSize = CHUNK_SIZE;
        const totalChunks = Math.ceil(file.size / chunkSize);

        for (let i = 0; i < totalChunks; i++) {
            // Check if still connected
            if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
                state.phase = 'error';
                state.error = 'Connection lost during upload';
                updateUploadCard(state);
                return;
            }

            const start = i * chunkSize;
            const end = Math.min(start + chunkSize, file.size);
            const chunk = file.slice(start, end);
            const arrayBuffer = await chunk.arrayBuffer();

            // Send binary frame
            state.ws.send(arrayBuffer);

            // Update local progress
            state.progress = ((i + 1) / totalChunks) * 95;  // 95% for upload, 5% for server processing
            state.speed = (end / ((Date.now() - state.startTime) / 1000));
            const remaining = file.size - end;
            state.eta = state.speed > 0 ? remaining / state.speed : null;
            updateUploadCard(state);
            updateOverallProgress();
        }

        // Signal finish
        state.ws.send(JSON.stringify({ type: 'finish' }));

    } catch (err) {
        console.error('Stream error:', err);
        state.phase = 'error';
        state.error = err.message;
        updateUploadCard(state);
        updateOverallProgress();
    }
}

function cleanupWs(ws) {
    const idx = wsConnections.indexOf(ws);
    if (idx !== -1) wsConnections.splice(idx, 1);
    // Try to start queued uploads
    processUploadQueue();
}

function cancelUpload(uploadId) {
    const state = activeUploads.get(uploadId);
    if (state && state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ type: 'cancel' }));
        state.ws.close();
    }
    cleanupWs(state?.ws);
    activeUploads.delete(uploadId);
}

// ─── UI: Upload Cards ───
function createUploadCard(state) {
    const container = document.getElementById('active-uploads');
    if (!container) return;

    const card = document.createElement('div');
    card.className = 'upload-progress';
    card.id = `upload-card-${state.id}`;
    card.innerHTML = getUploadCardHTML(state);
    container.prepend(card);
}

function updateUploadCard(state) {
    const card = document.getElementById(`upload-card-${state.id}`);
    if (card) card.innerHTML = getUploadCardHTML(state);
}

function getUploadCardHTML(state) {
    const phaseLabel = {
        'connecting': 'กำลังเชื่อมต่อ...',
        'handshake': 'กำลังเริ่มต้น...',
        'uploading': 'กำลังอัพโหลด...',
        'uploading_chunk': 'กำลังอัพโหลดไป Drive...',
        'splitting': 'กำลังแบ่งไฟล์...',
        'finalizing': 'กำลังบันทึก...',
        'complete': 'สำเร็จ!',
        'error': 'ล้มเหลว',
        'cancelled': 'ยกเลิก',
    };

    const isDone = state.phase === 'complete';
    const isError = state.phase === 'error';
    const isCancelled = state.phase === 'cancelled';
    const pct = Math.min(100, Math.max(0, state.progress)).toFixed(1);
    const speed = state.speed > 0 ? formatBytes(state.speed) + '/s' : '';
    const eta = state.eta != null && state.eta > 0 ? formatEta(state.eta) : '';
    const statusColor = isDone ? 'var(--success)' : isError ? 'var(--danger)' : isCancelled ? 'var(--warning)' : 'var(--accent)';

    return `
        <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.5rem">
            <span style="font-size:1.2rem;min-width:30px;text-align:center">
                ${isDone ? '✅' : isError ? '❌' : isCancelled ? '⛔' : '📤'}
            </span>
            <div style="flex:1;min-width:0">
                <div style="display:flex;justify-content:space-between;align-items:baseline;gap:0.5rem">
                    <strong style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${state.filename}">${state.filename}</strong>
                    <span style="color:var(--text-muted);font-size:0.8rem;white-space:nowrap">${formatBytes(state.fileSize)}</span>
                </div>
                <div class="progress-bar" style="margin:0.4rem 0">
                    <div class="progress-fill" style="width:${pct}%;background:${statusColor}"></div>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;color:var(--text-muted)">
                    <span>${phaseLabel[state.phase] || state.phase}${state.error ? ': ' + state.error : ''}</span>
                    <span>${pct}%${speed ? ' • ' + speed : ''}${eta ? ' • ~' + eta : ''}${isDone && state.elapsed ? ' • ' + state.elapsed.toFixed(1) + 's' : ''}</span>
                </div>
                ${isDone && state.isSplit ? `<div style="font-size:0.8rem;color:var(--text-muted);margin-top:0.25rem">✂️ แบ่งเป็น ${state.numChunks} ส่วน ${state.chunks ? state.chunks.map(c => '• ' + c.drive).join(' ') : ''}</div>` : ''}
            </div>
            ${!isDone && !isError && !isCancelled ? `<button class="btn btn-sm btn-danger" onclick="cancelUpload('${state.id}')" title="ยกเลิก">✕</button>` : ''}
            ${isDone || isError || isCancelled ? `<button class="btn btn-sm" onclick="this.closest('.upload-progress').remove();activeUploads.delete('${state.id}')" title="ลบ">✕</button>` : ''}
        </div>
    `;
}

function formatEta(seconds) {
    if (seconds < 60) return Math.round(seconds) + 's';
    if (seconds < 3600) return Math.round(seconds / 60) + 'm ' + Math.round(seconds % 60) + 's';
    return Math.round(seconds / 3600) + 'h ' + Math.round((seconds % 3600) / 60) + 'm';
}

// ─── Overall Progress ───
function updateOverallProgress() {
    const container = document.getElementById('upload-overall');
    if (!container) return;

    const states = Array.from(activeUploads.values());
    const active = states.filter(s => s.phase !== 'complete' && s.phase !== 'error' && s.phase !== 'cancelled');

    if (active.length === 0 && uploadQueue.length === 0) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'block';

    const totalFiles = states.length;
    const doneFiles = states.filter(s => s.phase === 'complete').length;
    const totalSize = states.reduce((a, s) => a + s.fileSize, 0);
    const processedSize = states.reduce((a, s) => a + (s.fileSize * s.progress / 100), 0);
    const overallPct = totalSize > 0 ? (processedSize / totalSize * 100).toFixed(1) : '0';
    const totalSpeed = active.reduce((a, s) => a + s.speed, 0);
    const maxEta = active.reduce((max, s) => s.eta != null ? Math.max(max, s.eta) : max, 0);

    document.getElementById('upload-total-count').textContent = `${doneFiles}/${totalFiles}`;
    document.getElementById('upload-total-speed').textContent = totalSpeed > 0 ? formatBytes(totalSpeed) + '/s' : '';
    document.getElementById('upload-overall-fill').style.width = overallPct + '%';
    document.getElementById('upload-overall-pct').textContent = overallPct + '%';
    document.getElementById('upload-overall-eta').textContent = maxEta > 0 ? '~' + formatEta(maxEta) + ' เหลือ' : '';
}

// ════════════════ Search ════════════════

async function doSearch() {
    const query = document.getElementById('search-input').value.trim();
    const container = document.getElementById('search-results');

    if (!query) {
        container.innerHTML = '<div class="empty-state"><p>พิมพ์คำค้นหา...</p></div>';
        return;
    }

    container.innerHTML = '<div class="loading">กำลังค้นหา...</div>';

    try {
        const res = await fetch(`${API}/api/search?q=${encodeURIComponent(query)}`);
        const data = await res.json();

        if (data.results.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🔍</div>
                    <p>ไม่พบผลลัพธ์สำหรับ "${query}"</p>
                </div>`;
            return;
        }

        container.innerHTML = `
            <p style="color:var(--text-muted);margin-bottom:1rem">พบ ${data.results.length} ผลลัพธ์</p>
        ` + data.results.map(f => `
            <div class="file-item" onclick="showFileDetail(${f.file_id})">
                <div class="file-icon">${getFileIcon(f.filename, f.is_split)}</div>
                <div class="file-info">
                    <div class="file-name">
                        ${f.filename}
                        ${f.is_split ? '<span class="split-badge">✂️ ' + f.num_chunks + ' ส่วน</span>' : ''}
                    </div>
                    <div class="file-meta">
                        ${formatBytes(f.size)} • ${f.folder}
                        ${f.tags.length ? ' • ' + f.tags.map(t => `<span class="tag">${t}</span>`).join(' ') : ''}
                    </div>
                </div>
            </div>
        `).join('');

    } catch (err) {
        container.innerHTML = '<div class="empty-state"><p>เกิดข้อผิดพลาดในการค้นหา</p></div>';
    }
}

// ════════════════ Accounts ════════════════

async function loadAccounts() {
    const container = document.getElementById('account-list');
    try {
        const res = await fetch(`${API}/api/accounts`);
        const data = await res.json();

        if (data.accounts.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">👤</div><p>ยังไม่มีบัญชีที่เพิ่มไว้</p></div>';
            return;
        }

        container.innerHTML = data.accounts.map(a => `
            <div class="account-item">
                <div class="account-avatar">${a.email[0].toUpperCase()}</div>
                <div class="account-info">
                    <div class="account-email">${a.email}</div>
                    <div class="account-status">
                        <span class="status-dot ${a.is_authorized ? 'status-active' : 'status-pending'}"></span>
                        ${a.is_authorized ? 'เชื่อมต่อแล้ว' : 'รอการเชื่อมต่อ'}
                        • ${new Date(a.created_at).toLocaleDateString('th-TH')}
                    </div>
                </div>
                <div class="file-actions">
                    ${!a.is_authorized ? `<button class="btn btn-sm btn-success" onclick="startAuth(${a.id})">🔗 เชื่อมต่อ Drive</button>` : ''}
                    <button class="btn btn-sm btn-danger" onclick="removeAccount(${a.id})">🗑️</button>
                </div>
            </div>
        `).join('');

    } catch (err) {
        container.innerHTML = '<div class="empty-state"><p>เกิดข้อผิดพลาด</p></div>';
    }
}

async function addAccount(e) {
    e.preventDefault();
    const email = document.getElementById('acc-email').value;
    const password = document.getElementById('acc-password').value;

    try {
        const formData = new FormData();
        formData.append('email', email);
        formData.append('password', password);

        const res = await fetch(`${API}/api/accounts`, {
            method: 'POST',
            body: formData,
        });

        const data = await res.json();
        if (res.ok) {
            showToast(`เพิ่มบัญชี ${email} สำเร็จ`);
            document.getElementById('add-account-form').reset();
            loadAccounts();
        } else {
            showToast(data.detail || 'เกิดข้อผิดพลาด', 'error');
        }
    } catch (err) {
        showToast('เกิดข้อผิดพลาด', 'error');
    }
}

async function removeAccount(id) {
    if (!confirm('ต้องการลบบัญชีนี้จริงหรือไม่?')) return;
    try {
        await fetch(`${API}/api/accounts/${id}`, { method: 'DELETE' });
        showToast('ลบบัญชีสำเร็จ');
        loadAccounts();
    } catch (err) {
        showToast('เกิดข้อผิดพลาด', 'error');
    }
}

async function startAuth(accountId) {
    try {
        const res = await fetch(`${API}/api/auth/url/${accountId}`);
        const data = await res.json();
        if (data.auth_url) {
            window.open(data.auth_url, '_blank', 'width=600,height=700');
        }
    } catch (err) {
        showToast('เกิดข้อผิดพลาด', 'error');
    }
}

// ════════════════ Drives ════════════════

async function loadDrives() {
    const container = document.getElementById('drive-details');
    try {
        const res = await fetch(`${API}/api/drives`);
        const data = await res.json();

        if (data.drives.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">💾</div><p>ยังไม่มี Drive ที่เชื่อมต่อ</p></div>';
        } else {
            container.innerHTML = data.drives.map(d => `
                <div class="drive-card">
                    <div class="drive-email">📧 ${d.email}</div>
                    <div class="drive-quota" style="margin-top:0.5rem">
                        <span>💾 ทั้งหมด: ${formatBytes(d.total_bytes)}</span>
                        <span>📊 ใช้แล้ว: ${formatBytes(d.used_bytes)}</span>
                        <span>✅ ว่าง: ${formatBytes(d.available_bytes)}</span>
                    </div>
                    ${d.last_synced ? `<div class="drive-quota" style="margin-top:0.5rem;font-size:0.8rem;color:var(--text-muted)">ซิงค์ล่าสุด: ${new Date(d.last_synced).toLocaleString('th-TH')}</div>` : ''}
                </div>
            `).join('');
        }

        // Load sync status for drives tab
        try {
            const syncRes = await fetch(`${API}/api/drives/sync/status`);
            const s = await syncRes.json();
            const dot = document.getElementById('drives-sync-dot');
            const text = document.getElementById('drives-sync-text');
            const details = document.getElementById('drives-sync-details');

            if (s.is_running) {
                dot.className = 'status-dot status-pending';
                text.textContent = 'Background Sync: กำลังซิงค์...';
            } else if (s.last_sync_result === 'ok') {
                dot.className = 'status-dot status-active';
                text.textContent = 'Background Sync: ซิงค์สำเร็จ';
            } else if (s.last_sync_result === 'error') {
                dot.className = 'status-dot status-inactive';
                text.textContent = `Background Sync: ล้มเหลว (${s.consecutive_errors}x)`;
            } else {
                dot.className = 'status-dot status-pending';
                text.textContent = 'Background Sync: รอการซิงค์...';
            }

            details.innerHTML = `
                <span>ครั้งที่ซิงค์: ${s.total_syncs}</span>
                <span>ล่าสุด: ${s.last_sync_at ? new Date(s.last_sync_at).toLocaleString('th-TH') : '--'}</span>
                <span>ถัดไป: ${s.next_sync_at ? new Date(s.next_sync_at).toLocaleString('th-TH') : '--'}</span>
                <span>ใช้เวลา: ${s.last_sync_duration_seconds != null ? s.last_sync_duration_seconds + 's' : '--'}</span>
                <span>ช่วง: ${Math.round(s.interval_seconds / 60)} นาที</span>
            `;
        } catch(e) {}

    } catch (err) {
        container.innerHTML = '<div class="empty-state"><p>เกิดข้อผิดพลาด</p></div>';
    }
}

async function syncDrives() {
    showToast('กำลังซิงค์...');
    try {
        const res = await fetch(`${API}/api/drives/sync`, { method: 'POST' });
        const data = await res.json();
        showToast('ซิงค์สำเร็จ');
        loadDrives();
    } catch (err) {
        showToast('ซิงค์ล้มเหลว', 'error');
    }
}

// ════════════════ Init ════════════════

document.addEventListener('DOMContentLoaded', () => {
    // Close modal on outside click
    document.getElementById('file-modal')?.addEventListener('click', e => {
        if (e.target.classList.contains('modal')) closeModal();
    });

    // Load dashboard by default
    loadDashboard();
});
