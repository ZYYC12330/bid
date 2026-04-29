/**
 * Word文档知识库插入系统 - 前端逻辑
 */

// ===== 状态管理 =====
let currentFileId = null;
let knowledgeList = [];

// ===== DOM 元素 =====
const elements = {
    uploadZone: document.getElementById('uploadZone'),
    fileInput: document.getElementById('fileInput'),
    fileInfo: document.getElementById('fileInfo'),
    fileName: document.getElementById('fileName'),
    fileStatus: document.getElementById('fileStatus'),
    previewSection: document.getElementById('previewSection'),
    previewContent: document.getElementById('previewContent'),
    actionButtons: document.getElementById('actionButtons'),
    resultSection: document.getElementById('resultSection'),
    resultInfo: document.getElementById('resultInfo'),
    insertionsList: document.getElementById('insertionsList'),
    downloadBtn: document.getElementById('downloadBtn'),
    knowledgeList: document.getElementById('knowledgeList'),
    knowledgeModal: document.getElementById('knowledgeModal'),
    knowledgeForm: document.getElementById('knowledgeForm'),
    loadingOverlay: document.getElementById('loadingOverlay'),
    loadingText: document.getElementById('loadingText')
};

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    initUpload();
    loadKnowledge();
});

// ===== 上传功能 =====
function initUpload() {
    // 点击上传
    elements.uploadZone.addEventListener('click', () => {
        elements.fileInput.click();
    });

    // 文件选择
    elements.fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            uploadFile(e.target.files[0]);
        }
    });

    // 拖拽上传
    elements.uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        elements.uploadZone.classList.add('dragover');
    });

    elements.uploadZone.addEventListener('dragleave', () => {
        elements.uploadZone.classList.remove('dragover');
    });

    elements.uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        elements.uploadZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            uploadFile(e.dataTransfer.files[0]);
        }
    });
}

async function uploadFile(file) {
    if (!file.name.endsWith('.docx')) {
        alert('只支持 .docx 格式文件');
        return;
    }

    showLoading('上传文件中...');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '上传失败');
        }

        const data = await response.json();
        currentFileId = data.file_id;

        // 更新UI
        elements.fileName.textContent = file.name;
        elements.fileStatus.textContent = '已上传';
        elements.uploadZone.classList.add('hidden');
        elements.fileInfo.classList.remove('hidden');
        elements.actionButtons.classList.remove('hidden');

        // 加载预览
        await loadPreview();

    } catch (error) {
        alert('上传失败: ' + error.message);
    } finally {
        hideLoading();
    }
}

async function loadPreview() {
    if (!currentFileId) return;

    try {
        const response = await fetch(`/api/preview/${currentFileId}`);
        if (response.ok) {
            const data = await response.json();
            elements.previewContent.textContent = data.text_content;
            elements.previewSection.classList.remove('hidden');
        }
    } catch (error) {
        console.error('预览加载失败:', error);
    }
}

function clearFile() {
    currentFileId = null;
    elements.fileInput.value = '';
    elements.uploadZone.classList.remove('hidden');
    elements.fileInfo.classList.add('hidden');
    elements.previewSection.classList.add('hidden');
    elements.actionButtons.classList.add('hidden');
    elements.resultSection.classList.add('hidden');
}

// ===== 文档处理 =====
async function processDocument() {
    if (!currentFileId) {
        alert('请先上传文档');
        return;
    }

    if (knowledgeList.length === 0) {
        alert('知识库为空，请先添加知识条目');
        return;
    }

    showLoading('正在分析文档并插入知识...');

    try {
        const response = await fetch(`/api/process/${currentFileId}`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '处理失败');
        }

        const data = await response.json();

        // 显示结果
        elements.resultInfo.innerHTML = `
            <p>✅ 处理完成！共找到 <strong>${data.insertions_count}</strong> 个可插入位置</p>
        `;

        // 显示插入详情
        if (data.insertions && data.insertions.length > 0) {
            elements.insertionsList.innerHTML = data.insertions.map((ins, index) => `
                <div class="insertion-item ${ins.status === 'success' ? 'success' : 'failed'}">
                    <strong>${ins.type === 'check' ? '☑' : '📝'} ${ins.label || '未知'}</strong>: 
                    ${ins.value || '-'}
                    <em class="${ins.status}">(${ins.status === 'success' ? '成功' : '失败'})</em>
                </div>
            `).join('');
        } else {
            elements.insertionsList.innerHTML = '<p>无修改详情</p>';
        }

        // 设置下载按钮
        elements.downloadBtn.onclick = () => {
            window.location.href = `/api/download/${currentFileId}`;
        };

        elements.resultSection.classList.remove('hidden');
        elements.actionButtons.classList.add('hidden');

    } catch (error) {
        alert('处理失败: ' + error.message);
    } finally {
        hideLoading();
    }
}

// ===== 知识库管理 =====
async function loadKnowledge() {
    try {
        const response = await fetch('/api/knowledge');
        if (response.ok) {
            knowledgeList = await response.json();
            renderKnowledgeList();
        }
    } catch (error) {
        console.error('加载知识库失败:', error);
    }
}

function renderKnowledgeList() {
    if (knowledgeList.length === 0) {
        elements.knowledgeList.innerHTML = `
            <div class="empty-state">
                <div class="icon">📚</div>
                <p>知识库为空</p>
                <p>点击上方按钮添加知识条目</p>
            </div>
        `;
        return;
    }

    elements.knowledgeList.innerHTML = knowledgeList.map(item => `
        <div class="knowledge-item" data-id="${item.id}">
            <div class="knowledge-item-header">
                <span class="knowledge-field">${escapeHtml(item.field_name)}</span>
                <div class="knowledge-actions">
                    <button onclick="editKnowledge('${item.id}')" title="编辑">✏️</button>
                    <button onclick="deleteKnowledge('${item.id}')" title="删除">🗑️</button>
                </div>
            </div>
            <div class="knowledge-content">${escapeHtml(item.content)}</div>
            ${item.description ? `<div class="knowledge-desc">${escapeHtml(item.description)}</div>` : ''}
        </div>
    `).join('');
}

function showAddKnowledgeModal() {
    document.getElementById('modalTitle').textContent = '添加知识条目';
    document.getElementById('knowledgeId').value = '';
    document.getElementById('fieldName').value = '';
    document.getElementById('content').value = '';
    document.getElementById('description').value = '';
    elements.knowledgeModal.classList.remove('hidden');
}

function editKnowledge(id) {
    const item = knowledgeList.find(k => k.id === id);
    if (!item) return;

    document.getElementById('modalTitle').textContent = '编辑知识条目';
    document.getElementById('knowledgeId').value = id;
    document.getElementById('fieldName').value = item.field_name;
    document.getElementById('content').value = item.content;
    document.getElementById('description').value = item.description || '';
    elements.knowledgeModal.classList.remove('hidden');
}

function closeModal() {
    elements.knowledgeModal.classList.add('hidden');
}

async function saveKnowledge(event) {
    event.preventDefault();

    const id = document.getElementById('knowledgeId').value;
    const data = {
        field_name: document.getElementById('fieldName').value,
        content: document.getElementById('content').value,
        description: document.getElementById('description').value
    };

    showLoading('保存中...');

    try {
        const url = id ? `/api/knowledge/${id}` : '/api/knowledge';
        const method = id ? 'PUT' : 'POST';

        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (!response.ok) {
            throw new Error('保存失败');
        }

        closeModal();
        await loadKnowledge();

    } catch (error) {
        alert('保存失败: ' + error.message);
    } finally {
        hideLoading();
    }
}

async function deleteKnowledge(id) {
    if (!confirm('确定要删除这个知识条目吗？')) {
        return;
    }

    showLoading('删除中...');

    try {
        const response = await fetch(`/api/knowledge/${id}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error('删除失败');
        }

        await loadKnowledge();

    } catch (error) {
        alert('删除失败: ' + error.message);
    } finally {
        hideLoading();
    }
}

// ===== 工具函数 =====
function showLoading(text = '处理中...') {
    elements.loadingText.textContent = text;
    elements.loadingOverlay.classList.remove('hidden');
}

function hideLoading() {
    elements.loadingOverlay.classList.add('hidden');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
