/* ─── State ─── */
let currentRepoId = null;
let currentRepo = null;
let selectedModel = '';
let contextMenuRepoId = null;
let contextMenuRepoIsOwner = false;
let pendingTempCloneKey = null;
let _countdownTimer = null;
let _wcRefreshTimer = null;
let isStreaming = false;

/* ─── Init ─── */
document.addEventListener('DOMContentLoaded', async () => {
  await initUser();
  await loadModels();
  await loadRepos();
  await loadWorldCup();
  document.addEventListener('click', hideContextMenu);
});

/* ─── User ─── */
async function initUser() {
  try {
    const storedId = localStorage.getItem('user_id');
    const url = storedId ? `/api/me?stored_id=${encodeURIComponent(storedId)}` : '/api/me';
    const data = await api('GET', url);
    if (data && data.user_id) {
      localStorage.setItem('user_id', data.user_id);
    }
  } catch (e) { /* cookie will be set */ }
}

/* ─── API helper ─── */
async function api(method, path, body) {
  const opts = { method, credentials: 'include', headers: {} };
  if (body) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

/* ─── Models ─── */
async function loadModels() {
  try {
    const models = await api('GET', '/api/models');
    const sel = document.getElementById('model-selector');
    sel.innerHTML = models.map(m => `<option value="${m.id}">${m.name}</option>`).join('');
    selectedModel = sel.value;
  } catch {}
}

/* ─── Repos ─── */
async function loadRepos() {
  try {
    const repos = await api('GET', '/api/repos');
    renderRepos(repos);
    // Auto-select repo from URL on first load
    if (!currentRepoId && repos.length) {
      const params = new URLSearchParams(window.location.search);
      const repoIdFromUrl = parseInt(params.get('repo'));
      if (repoIdFromUrl && repos.find(r => r.id === repoIdFromUrl)) {
        await selectRepo(repoIdFromUrl);
      }
    }
  } catch (e) {
    document.getElementById('repo-list').innerHTML = `<div style="padding:12px;color:var(--red);font-size:12px;">Error: ${e.message}</div>`;
  }
}

function renderRepos(repos) {
  const list = document.getElementById('repo-list');
  if (!repos.length) {
    list.innerHTML = '<div style="padding:16px 12px;color:var(--text-2);font-size:12px;">Chưa có repository nào.<br/>Nhấn nút + để thêm mới.</div>';
    return;
  }
  list.innerHTML = repos.map(r => `
    <div class="repo-item ${r.id === currentRepoId ? 'active' : ''}" onclick="selectRepo(${r.id})" data-id="${r.id}">
      <span class="repo-icon">📁</span>
      <span class="repo-name" title="${r.name}">${r.name}</span>
      ${!r.is_owner ? `<span class="repo-public-badge" title="Public repository"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg></span>` : ''}
      <span class="repo-status ${r.clone_status}" title="${r.clone_status}"></span>
      <button class="repo-menu-btn" onclick="openContextMenu(event,${r.id},${r.is_owner})" title="Options" ${r.is_owner ? '' : 'style="display:none"'}>⋯</button>
    </div>
  `).join('');
}

async function selectRepo(id) {
  currentRepoId = id;
  history.replaceState(null, '', `?repo=${id}`);
  try {
    currentRepo = await api('GET', `/api/repos/${id}`);
    document.getElementById('current-repo-label').innerHTML =
      `<span>${currentRepo.name}</span>`;
    loadRepos(); // refresh statuses
    showChatArea();
    await loadHistory();
  } catch (e) { toast(e.message, 'error'); }
}

function showChatArea() {
  document.getElementById('welcome').style.display = 'none';
  document.getElementById('messages').style.display = 'none'; // hidden until msgs loaded
  document.getElementById('chat-bottom').style.display = 'block';
  document.getElementById('empty-hint').style.display = 'block';
  const ca = document.getElementById('chat-area');
  ca.classList.remove('has-messages');
  ca.classList.add('empty');
}

function _setChatHasMessages(has) {
  const ca = document.getElementById('chat-area');
  const clearBtn = document.getElementById('clear-btn');
  if (has) {
    ca.classList.remove('empty');
    ca.classList.add('has-messages');
    document.getElementById('empty-hint').style.display = 'none';
    document.getElementById('messages').style.display = 'flex';
    if (clearBtn) clearBtn.style.display = '';
  } else {
    ca.classList.remove('has-messages');
    ca.classList.add('empty');
    document.getElementById('empty-hint').style.display = 'block';
    document.getElementById('messages').style.display = 'none';
    if (clearBtn) clearBtn.style.display = 'none';
  }
}

/* ─── Chat history ─── */
async function loadHistory() {
  if (!currentRepoId) return;
  try {
    const msgs = await api('GET', `/api/chat/${currentRepoId}/history`);
    const el = document.getElementById('messages');
    el.innerHTML = '';
    if (msgs.length > 0) {
      _setChatHasMessages(true);
      msgs.forEach(m => appendMessage(m.role, m.content, false));
      el.scrollTop = el.scrollHeight;
      renderMermaidIn(el).catch(() => {});
    } else {
      _setChatHasMessages(false);
    }
  } catch {}
}

async function clearHistory() {
  if (!currentRepoId) return;
  if (!confirm('Xóa toàn bộ lịch sử chat?')) return;
  try {
    await api('DELETE', `/api/chat/${currentRepoId}/history`);
    document.getElementById('messages').innerHTML = '';
    _setChatHasMessages(false);
    toast('Đã xóa lịch sử chat');
  } catch (e) { toast(e.message, 'error'); }
}

/* ─── Send message ─── */
function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function sendSuggestion(text) {
  document.getElementById('msg-input').value = text;
  sendMessage();
}

async function pullCurrentRepo() {
  if (!currentRepoId) return;
  const btn = document.getElementById('pull-chip');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '⏳ Đang pull…';
  try {
    const res = await api('POST', `/api/repos/${currentRepoId}/pull`);
    const branch = res.branch ? ` (branch: ${res.branch})` : '';
    const msg = res.output || 'Already up to date.';
    toast(`✓ Pull thành công${branch}: ${msg.split('\n')[0]}`, 'success');
  } catch (e) {
    toast(`✗ Pull thất bại: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

async function sendMessage() {
  if (isStreaming) return;
  const input = document.getElementById('msg-input');
  const text = input.value.trim();
  if (!text || !currentRepoId) return;

  input.value = '';
  input.style.height = 'auto';
  appendMessage('user', text);

  isStreaming = true;
  document.getElementById('send-btn').disabled = true;

  const typingId = appendTyping();

  try {
    const res = await fetch(`/api/chat/${currentRepoId}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, model: selectedModel }),
    });

    if (!res.ok) { throw new Error(`HTTP ${res.status}`); }

    removeTyping(typingId);
    const msgEl = appendMessage('assistant', '', true);
    const bubble = msgEl.querySelector('.msg-bubble');
    let fullText = '';

    // Streaming cursor
    const cursor = document.createElement('span');
    cursor.className = 'stream-cursor';
    bubble.appendChild(cursor);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        try {
          const data = JSON.parse(line.slice(5).trim());
          if (data.content) {
            fullText += data.content;
            bubble.innerHTML = renderMarkdown(fullText);
            bubble.appendChild(cursor);
            document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
          }
          if (data.done) break;
        } catch {}
      }
    }

    // Remove cursor, show done badge
    cursor.remove();
    const doneBadge = document.createElement('div');
    doneBadge.className = 'stream-done-badge';
    doneBadge.innerHTML = '✓ Đã hoàn thành';
    msgEl.appendChild(doneBadge);
    setTimeout(() => doneBadge.classList.add('fade-out'), 2500);
    setTimeout(() => doneBadge.remove(), 3200);

    // Render any mermaid diagrams in the final response
    renderMermaidIn(bubble).catch(() => {});
  } catch (e) {
    removeTyping(typingId);
    appendMessage('assistant', `⚠️ ${e.message}`);
  } finally {
    isStreaming = false;
    document.getElementById('send-btn').disabled = false;
  }
}

function appendMessage(role, content, empty = false) {
  _setChatHasMessages(true);
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.innerHTML = `<div class="msg-bubble">${empty ? '' : (role === 'user' ? escapeHtml(content) : renderMarkdown(content))}</div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function appendTyping() {
  const msgs = document.getElementById('messages');
  const id = 'typing-' + Date.now();
  const div = document.createElement('div');
  div.id = id;
  div.className = 'message assistant';
  div.innerHTML = `<div class="msg-bubble typing-bubble">
    <div class="typing-indicator">
      <div class="typing-dots">
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
      </div>
      <span class="typing-label">Đang phân tích…</span>
    </div>
  </div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return id;
}
function removeTyping(id) { document.getElementById(id)?.remove(); }

/* ─── Mermaid renderer ─── */
let _mmdCounter = 0;

function _fixMermaidSrc(src) {
  // Remove YAML front matter (---...---) that some LLMs add
  src = src.replace(/^---[\s\S]*?---\s*/m, '');
  // Remove leading/trailing blank lines
  src = src.trim();
  // Quote unquoted participant/actor names that contain spaces or non-ASCII
  // e.g. "participant Người dùng" → "participant Người dùng as \"Người dùng\""
  src = src.replace(/^(\s*(?:participant|actor)\s+)([^\n"]+?)(\s+as\s+.*)?$/gm, (_, prefix, name, alias) => {
    name = name.trim();
    if (alias) return prefix + name + alias;
    // If name has spaces or non-ASCII → add as alias with quotes
    if (/[\s-￿]/.test(name)) {
      const safe = name.replace(/\s+/g, '_').replace(/[^\w]/g, '');
      return `${prefix}${safe} as "${name}"`;
    }
    return prefix + name;
  });
  return src;
}

async function renderMermaidIn(el) {
  const blocks = el.querySelectorAll('.mermaid-block[data-mmd]');
  for (const block of blocks) {
    if (block.dataset.rendered) continue;
    block.dataset.rendered = '1';
    const src = _fixMermaidSrc(decodeURIComponent(atob(block.dataset.mmd)));
    const diagEl = block.querySelector('.mermaid-diagram');
    try {
      const id = 'mmd-' + (++_mmdCounter);
      const { svg } = await mermaid.render(id, src);
      diagEl.innerHTML = svg;
      diagEl.addEventListener('click', () => openDiagramModal(svg));
    } catch (e) {
      diagEl.innerHTML = `<div class="mermaid-error">⚠ Diagram error: ${escapeHtml(String(e.message || e))}</div>`;
      diagEl.style.cursor = 'default';
    }
  }
}

function openDiagramModal(svgHtml) {
  document.getElementById('diagram-modal-content').innerHTML = svgHtml;
  document.getElementById('diagram-modal').classList.add('open');
  document.addEventListener('keydown', _diagEsc);
}
function closeDiagramModal(e) {
  if (e && e.target !== document.getElementById('diagram-modal') && e.target !== document.getElementById('diagram-modal-close')) return;
  document.getElementById('diagram-modal').classList.remove('open');
  document.removeEventListener('keydown', _diagEsc);
}
function _diagEsc(e) { if (e.key === 'Escape') closeDiagramModal({ target: document.getElementById('diagram-modal') }); }

/* ─── Markdown renderer (simple) ─── */
function renderMarkdown(text) {
  // Strip outer ```markdown wrapper that LLMs sometimes add around the whole response
  text = text.replace(/^```(?:markdown|md)\n([\s\S]*?)```\s*$/m, (_, inner) => inner.trim());
  // Mermaid diagrams — extract before general code blocks
  text = text.replace(/```mermaid\n?([\s\S]*?)```/g, (_, code) => {
    const encoded = btoa(encodeURIComponent(code.trim()));
    return `<div class="mermaid-block" data-mmd="${encoded}">
      <div class="mermaid-diagram">⏳ Rendering diagram…</div>
      <details class="mermaid-src-toggle">
        <summary>Source</summary>
        <pre><code>${escapeHtml(code.trim())}</code></pre>
      </details>
    </div>`;
  });
  // Code blocks
  text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre><code class="lang-${lang}">${escapeHtml(code.trim())}</code></pre>`;
  });
  // Inline code
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Italic
  text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // Headings
  text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  text = text.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  text = text.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // Unordered lists
  text = text.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
  text = text.replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`);
  // Ordered lists
  text = text.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  // Blockquotes
  text = text.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>');
  // Links
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  // Line breaks to paragraphs
  text = text.replace(/\n\n+/g, '</p><p>');
  text = text.replace(/\n/g, '<br/>');
  text = `<p>${text}</p>`;
  // Cleanup empty paragraphs
  text = text.replace(/<p><\/p>/g, '');
  text = text.replace(/<p>(<h[1-3]>)/g, '$1');
  text = text.replace(/(<\/h[1-3]>)<\/p>/g, '$1');
  text = text.replace(/<p>(<pre>)/g, '$1');
  text = text.replace(/(<\/pre>)<\/p>/g, '$1');
  text = text.replace(/<p>(<ul>)/g, '$1');
  text = text.replace(/(<\/ul>)<\/p>/g, '$1');
  text = text.replace(/<p>(<blockquote>)/g, '$1');
  text = text.replace(/(<\/blockquote>)<\/p>/g, '$1');
  return text;
}

function escapeHtml(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ─── Add Repo Modal ─── */
function resetValidationState() {
  document.getElementById('validation-result').innerHTML = '';
  document.getElementById('submit-btn').disabled = true;
  pendingTempCloneKey = null;
}

function openAddRepo() {
  ['f-name','f-url','f-branch','f-username','f-token'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  document.getElementById('f-branch').value = 'main';
  ['f-private','f-interact','f-auto-docs','f-review-mr','f-review-commit','f-shared'].forEach(id => {
    const el = document.getElementById(id); if (el) el.checked = false;
  });
  const _pf = document.getElementById('private-fields'); if (_pf) _pf.style.display = 'none';
  const _ir = document.getElementById('f-interact-row'); if (_ir) _ir.style.display = 'none';
  const _af = document.getElementById('auto-features-group'); if (_af) _af.style.display = 'none';
  resetValidationState();
  document.getElementById('add-repo-modal').style.display = 'flex';
}

function togglePrivateFields() {
  const isPrivate = document.getElementById('f-private').checked;
  const interact = document.getElementById('f-interact').checked;
  const interactRow = document.getElementById('f-interact-row');
  const privateFields = document.getElementById('private-fields');
  const autoFeatures = document.getElementById('auto-features-group');

  interactRow.style.display = isPrivate ? 'flex' : 'none';
  const needsAuth = isPrivate || interact;
  privateFields.style.display = needsAuth ? 'block' : 'none';

  // Auto-features only available when "Tương tác với source" is enabled
  autoFeatures.style.display = interact ? 'flex' : 'none';
  if (!interact) {
    ['f-auto-docs', 'f-review-mr', 'f-review-commit'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.checked = false;
    });
  }
}

async function validateRepo() {
  const url = document.getElementById('f-url').value.trim();
  const branch = document.getElementById('f-branch').value.trim();
  if (!url || !branch) { toast('Nhập URL và branch trước', 'error'); return; }
  if (document.getElementById('f-private').checked) {
    const username = document.getElementById('f-username').value.trim();
    const token = document.getElementById('f-token').value.trim();
    if (!username || !token) {
      toast('Private repo yêu cầu nhập GitHub Username và Personal Access Token', 'error');
      return;
    }
  }

  const btn = document.getElementById('validate-btn');
  const div = document.getElementById('validation-result');
  btn.disabled = true; btn.textContent = 'Đang kiểm tra…';
  div.className = 'validation-result info';
  div.innerHTML = '⏳ Đang kiểm tra repository và clone source code, vui lòng đợi…';

  try {
    const username = document.getElementById('f-username').value.trim();
    const token = document.getElementById('f-token').value.trim();
    const validation = await api('POST', '/api/repos/validate-url', {
      github_url: url, main_branch: branch,
      github_username: username || null, github_token: token || null,
    });

    if (validation.valid) {
      pendingTempCloneKey = validation.temp_clone_key || null;
      div.className = 'validation-result ok';
      div.innerHTML = `✅ Repository hợp lệ & đã clone: <strong>${validation.repo_name}</strong><br/>
        Branch "${branch}": ${validation.branch_exists ? '✅' : '❌'} |
        Thư mục rules/: ${validation.has_rules_folder ? '✅' : '❌'} |
        rules/docs.md: ${validation.has_rules_docs ? '✅' : '⚠️ (chưa có — tắt auto-docs)'} |
        rules/review.md: ${validation.has_rules_review ? '✅' : '⚠️ (chưa có — tắt auto-review)'}
        <br/><span style="font-size:10px;color:var(--text-2)">Tạo rules/docs.md để bật viết tài liệu • Tạo rules/review.md để bật review commit/MR</span>`;
      document.getElementById('submit-btn').disabled = false;
    } else {
      pendingTempCloneKey = null;
      div.className = 'validation-result err';
      div.innerHTML = `❌ ${validation.error || 'Kiểm tra thất bại (không rõ lý do)'}`;
      document.getElementById('submit-btn').disabled = true;
    }
  } catch (e) {
    pendingTempCloneKey = null;
    div.className = 'validation-result err';
    div.innerHTML = `❌ ${e.message || 'Kiểm tra thất bại'}`;
    document.getElementById('submit-btn').disabled = true;
  } finally {
    btn.disabled = false; btn.textContent = '🔍 Kiểm tra';
  }
}

async function submitRepo() {
  const name = document.getElementById('f-name').value.trim();
  const url = document.getElementById('f-url').value.trim();
  const branch = document.getElementById('f-branch').value.trim();
  if (!name) { toast('Tên repository là bắt buộc', 'error'); return; }
  if (!url) { toast('GitHub URL là bắt buộc', 'error'); return; }
  if (!branch) { toast('Branch chính là bắt buộc', 'error'); return; }

  const isPrivate = document.getElementById('f-private').checked;
  const interact = document.getElementById('f-interact').checked;
  const username = document.getElementById('f-username').value.trim();
  const token = document.getElementById('f-token').value.trim();

  if (isPrivate && interact && !token) {
    toast('Cần nhập GitHub token cho private repo', 'error'); return;
  }

  const btn = document.getElementById('submit-btn');
  btn.disabled = true; btn.textContent = 'Đang thêm…';

  try {
    const body = {
      name, github_url: url, main_branch: branch,
      is_private: isPrivate, interact_with_source: interact,
      github_username: username || null,
      github_token: token || null,
      auto_update_docs: document.getElementById('f-auto-docs').checked,
      review_on_mr: document.getElementById('f-review-mr').checked,
      review_on_commit: document.getElementById('f-review-commit').checked,
      is_shared: document.getElementById('f-shared').checked,
      temp_clone_key: pendingTempCloneKey || null,
    };
    const created = await api('POST', '/api/repos', body);
    pendingTempCloneKey = null;
    closeModal('add-repo-modal');
    await loadRepos();
    toast('Repository đã thêm thành công' + (created.clone_status === 'ready' ? ' và sẵn sàng!' : '! Đang clone source code…'));
    if (created.id) selectRepo(created.id);
  } catch (e) {
    toast(e.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = 'Thêm Repository';
  }
}

/* ─── Context menu ─── */
function openContextMenu(e, repoId, isOwner) {
  e.stopPropagation();
  contextMenuRepoId = repoId;
  contextMenuRepoIsOwner = !!isOwner;
  const menu = document.getElementById('context-menu');
  // Show/hide delete button based on ownership
  const deleteBtn = menu.querySelector('[data-action="delete"]');
  if (deleteBtn) deleteBtn.style.display = contextMenuRepoIsOwner ? 'block' : 'none';
  menu.style.display = 'block';
  menu.style.left = e.pageX + 'px';
  menu.style.top = e.pageY + 'px';
}

function hideContextMenu() {
  document.getElementById('context-menu').style.display = 'none';
}

async function recloneRepo() {
  hideContextMenu();
  if (!contextMenuRepoId) return;
  try {
    await api('POST', `/api/repos/${contextMenuRepoId}/reclone`);
    toast('Re-cloning bắt đầu…');
    setTimeout(loadRepos, 2000);
  } catch (e) { toast(e.message, 'error'); }
}

async function showWebhookInfo() {
  hideContextMenu();
  if (!contextMenuRepoId) return;
  try {
    const repo = await api('GET', `/api/repos/${contextMenuRepoId}`);
    const base = window.location.origin;
    document.getElementById('wh-url').value = `${base}${repo.webhook_url}`;
    document.getElementById('wh-secret').value = repo.webhook_secret || '(not available)';
    document.getElementById('webhook-modal').style.display = 'flex';
  } catch (e) { toast(e.message, 'error'); }
}

async function deleteRepo() {
  hideContextMenu();
  if (!contextMenuRepoId) return;
  if (!contextMenuRepoIsOwner) { toast('Chỉ người tạo mới có quyền xóa repository này', 'error'); return; }
  if (!confirm('Xóa repository này? Toàn bộ lịch sử chat sẽ bị xóa.')) return;
  try {
    await api('DELETE', `/api/repos/${contextMenuRepoId}`);
    if (currentRepoId === contextMenuRepoId) {
      currentRepoId = null;
      currentRepo = null;
      document.getElementById('welcome').style.display = 'flex';
      document.getElementById('messages').style.display = 'none';
      document.getElementById('chat-bottom').style.display = 'none';
      document.getElementById('current-repo-label').innerHTML = '<span>Select a repository</span><span style="color:var(--text-2)">▾</span>';
    }
    await loadRepos();
    toast('Repository đã xóa');
  } catch (e) { toast(e.message, 'error'); }
}

/* ─── Helpers ─── */
function closeModal(id) { document.getElementById(id).style.display = 'none'; }
function closeModalOutside(e) { if (e.target === e.currentTarget) closeModal(e.currentTarget.id); }
function toggleWorldCupSidebar() {
  const sidebar = document.getElementById('worldcup-sidebar');
  sidebar.classList.toggle('wc-open');
}

function toggleSidebar() {
  const s = document.getElementById('sidebar');
  const btn = document.getElementById('sidebar-show-btn');
  const hidden = s.style.display === 'none';
  s.style.display = hidden ? '' : 'none';
  btn.style.display = hidden ? 'none' : 'inline-flex';
}

function copyText(id) {
  const el = document.getElementById(id);
  navigator.clipboard.writeText(el.value).then(() => toast('Đã copy!'));
}

function toast(msg, type = 'success') {
  const container = document.getElementById('toast');
  const el = document.createElement('div');
  el.className = `toast-msg ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

/* ─── World Cup ─── */
async function loadWorldCup() {
  try {
    const data = await api('GET', '/api/worldcup/today');
    renderWorldCup(data);
    startCountdowns();
    _scheduleWcRefresh(data);
  } catch {
    _scheduleWcRefresh(null);
  }
}

function _scheduleWcRefresh(data) {
  if (_wcRefreshTimer) clearTimeout(_wcRefreshTimer);
  const allMatches = [...(data?.upcoming || data?.today || []), ...(data?.recent || [])];
  const hasLive = allMatches.some(m => m.status === 'IN_PLAY');
  _wcRefreshTimer = setTimeout(loadWorldCup, 10 * 60 * 1000);
}

function startCountdowns() {
  if (_countdownTimer) clearInterval(_countdownTimer);
  _tickCountdowns();
  _countdownTimer = setInterval(_tickCountdowns, 1000);
}

function _tickCountdowns() {
  const now = Date.now();
  document.querySelectorAll('.match-countdown[data-utc]').forEach(el => {
    const diff = new Date(el.dataset.utc).getTime() - now;
    if (diff <= 0) {
      el.innerHTML = '🔴 LIVE';
      el.style.background = 'rgba(34,197,94,0.15)';
      el.style.color = '#22c55e';
      // Update status badge in the same match-item to "Đang diễn ra"
      const matchItem = el.closest('.match-item');
      if (matchItem) {
        const badge = matchItem.querySelector('.status-badge');
        if (badge && badge.textContent.trim() === 'Sắp diễn ra') {
          badge.textContent = 'Đang diễn ra';
          badge.classList.remove('scheduled');
          badge.classList.add('in-play');
        }
      }
      return;
    }
    const h = Math.floor(diff / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    const s = Math.floor((diff % 60000) / 1000);
    el.innerHTML = `⏱ ${String(h).padStart(2,'0')}h : ${String(m).padStart(2,'0')}m : ${String(s).padStart(2,'0')}s`;
  });
}

function renderWorldCup(data) {
  const container = document.getElementById('wc-content');
  const recent = data.recent || [];

  // Backend now returns pre-filtered upcoming (today + next days). Fallback for old shape.
  const upcoming = (data.upcoming || (data.today || []).filter(m => m.status !== 'FINISHED')).slice(0, 5);
  // All recent finished matches, up to 5
  const allFinished = recent.slice(0, 5);

  let html = '';

  if (upcoming.length) {
    html += `<div class="wc-card">
      <div class="wc-card-title">Trận sắp diễn ra</div>
      ${upcoming.map(m => renderMatch(m)).join('')}
    </div>`;
  }

  if (allFinished.length) {
    html += `<div class="wc-card">
      <div class="wc-card-title">Kết quả gần nhất</div>
      ${allFinished.map(m => renderMatch(m)).join('')}
    </div>`;
  }

  if (!html) {
    if (data.source === 'error') {
      html = `<div style="padding:16px 10px;text-align:center;color:var(--text-2);font-size:12px;">⚠️ Không thể tải dữ liệu<br/><span style="font-size:10px">${data.error || ''}</span></div>`;
    } else {
      html = '<div style="padding:20px;text-align:center;color:var(--text-2);font-size:12px;">Không có trận đấu World Cup hôm nay</div>';
    }
  }

  const sourceLabel = { espn: 'ESPN', thesportsdb: 'TheSportsDB' }[data.source] || '';
  if (sourceLabel) {
    html += `<div style="padding:4px 10px;font-size:10px;color:var(--text-2);text-align:right;">Nguồn: ${sourceLabel}</div>`;
  }

  container.innerHTML = html;
}

const _FLAGS = {
  'Afghanistan':'🇦🇫','Albania':'🇦🇱','Algeria':'🇩🇿','Angola':'🇦🇴','Argentina':'🇦🇷',
  'Armenia':'🇦🇲','Australia':'🇦🇺','Austria':'🇦🇹','Azerbaijan':'🇦🇿','Bahrain':'🇧🇭',
  'Belgium':'🇧🇪','Bolivia':'🇧🇴','Bosnia and Herzegovina':'🇧🇦','Bosnia & Herzegovina':'🇧🇦',
  'Brazil':'🇧🇷','Bulgaria':'🇧🇬','Burkina Faso':'🇧🇫','Cameroon':'🇨🇲','Canada':'🇨🇦',
  'Cape Verde':'🇨🇻','Chile':'🇨🇱','China':'🇨🇳','Colombia':'🇨🇴','Congo':'🇨🇬',
  'Costa Rica':'🇨🇷','Croatia':'🇭🇷','Cuba':'🇨🇺','Curaçao':'🇨🇼','Curacao':'🇨🇼',
  'Czech Republic':'🇨🇿','Czechia':'🇨🇿','DR Congo':'🇨🇩','Denmark':'🇩🇰',
  'Ecuador':'🇪🇨','Egypt':'🇪🇬','El Salvador':'🇸🇻','England':'🏴󠁧󠁢󠁥󠁮󠁧󠁿',
  'Finland':'🇫🇮','France':'🇫🇷','Gabon':'🇬🇦','Georgia':'🇬🇪','Germany':'🇩🇪',
  'Ghana':'🇬🇭','Greece':'🇬🇷','Guatemala':'🇬🇹','Guinea':'🇬🇳','Honduras':'🇭🇳',
  'Hungary':'🇭🇺','Iceland':'🇮🇸','India':'🇮🇳','Indonesia':'🇮🇩','Iran':'🇮🇷',
  'Iraq':'🇮🇶','Ireland':'🇮🇪','Israel':'🇮🇱','Italy':'🇮🇹',
  'Ivory Coast':'🇨🇮',"Côte d'Ivoire":'🇨🇮','Cote d\'Ivoire':'🇨🇮',
  'Jamaica':'🇯🇲','Japan':'🇯🇵','Jordan':'🇯🇴','Kazakhstan':'🇰🇿','Kenya':'🇰🇪',
  'Kuwait':'🇰🇼','Latvia':'🇱🇻','Lebanon':'🇱🇧','Libya':'🇱🇾','Lithuania':'🇱🇹',
  'Luxembourg':'🇱🇺','Malaysia':'🇲🇾','Mali':'🇲🇱','Malta':'🇲🇹','Mexico':'🇲🇽',
  'Moldova':'🇲🇩','Montenegro':'🇲🇪','Morocco':'🇲🇦','Mozambique':'🇲🇿',
  'Netherlands':'🇳🇱','New Zealand':'🇳🇿','Nigeria':'🇳🇬','North Korea':'🇰🇵',
  'North Macedonia':'🇲🇰','Norway':'🇳🇴','Oman':'🇴🇲','Palestine':'🇵🇸',
  'Panama':'🇵🇦','Paraguay':'🇵🇾','Peru':'🇵🇪','Philippines':'🇵🇭',
  'Poland':'🇵🇱','Portugal':'🇵🇹','Qatar':'🇶🇦','Romania':'🇷🇴',
  'Saudi Arabia':'🇸🇦','Scotland':'🏴󠁧󠁢󠁳󠁣󠁴󠁿','Senegal':'🇸🇳','Serbia':'🇷🇸',
  'Slovakia':'🇸🇰','Slovenia':'🇸🇮','South Africa':'🇿🇦',
  'South Korea':'🇰🇷','Korea Republic':'🇰🇷',
  'Spain':'🇪🇸','Sweden':'🇸🇪','Switzerland':'🇨🇭','Syria':'🇸🇾',
  'Thailand':'🇹🇭','Tunisia':'🇹🇳','Turkey':'🇹🇷','Türkiye':'🇹🇷',
  'UAE':'🇦🇪','United Arab Emirates':'🇦🇪','Ukraine':'🇺🇦',
  'Uruguay':'🇺🇾','USA':'🇺🇸','United States':'🇺🇸','Uzbekistan':'🇺🇿',
  'Venezuela':'🇻🇪','Vietnam':'🇻🇳','Wales':'🏴󠁧󠁢󠁷󠁬󠁳󠁿','Yemen':'🇾🇪',
  'Zambia':'🇿🇲','Zimbabwe':'🇿🇼',
};

function _flag(name) {
  if (!name) return '';
  if (_FLAGS[name]) return _FLAGS[name];
  const key = Object.keys(_FLAGS).find(k => k.toLowerCase() === name.toLowerCase());
  return key ? _FLAGS[key] : '';
}

/* ─── Matrix Rain Background ─── */
(function matrixRain() {
  const canvas = document.getElementById('matrix-bg');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const FONT_SIZE = 13;
  const CHARS = '01';
  let drops = [];

  function resize() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    const cols = Math.floor(canvas.width / FONT_SIZE);
    // Keep existing drops, extend or trim
    while (drops.length < cols) drops.push(Math.random() * -(canvas.height / FONT_SIZE));
    drops.length = cols;
  }

  function draw() {
    // Trail fade — higher alpha = shorter trails, more visible
    ctx.fillStyle = 'rgba(2,5,9,0.08)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.font = `${FONT_SIZE}px 'SF Mono','Fira Code',monospace`;
    const cols = Math.floor(canvas.width / FONT_SIZE);

    for (let i = 0; i < cols; i++) {
      const char = Math.random() > 0.5 ? '1' : '0';
      const y = drops[i] * FONT_SIZE;
      const r = Math.random();

      if (r > 0.97) {
        ctx.fillStyle = '#ffffff';                              // bright white flash
      } else if (r > 0.91) {
        ctx.fillStyle = 'rgba(88,166,255,0.95)';               // blue accent
      } else {
        const alpha = 0.55 + Math.random() * 0.45;            // brighter green (was 0.2)
        ctx.fillStyle = `rgba(63,185,80,${alpha.toFixed(2)})`;
      }

      ctx.fillText(char, i * FONT_SIZE, y);

      if (y > canvas.height && Math.random() > 0.972) {
        drops[i] = 0;
      }
      drops[i] += 0.4 + Math.random() * 0.4;
    }
  }

  resize();
  window.addEventListener('resize', resize);
  setInterval(draw, 45);
})();

function renderMatch(m) {
  const statusClass = { SCHEDULED: 'scheduled', IN_PLAY: 'in-play', FINISHED: 'finished' }[m.status] || 'scheduled';
  const scoreDisplay = m.status === 'SCHEDULED'
    ? `<span class="match-score">vs</span>`
    : `<span class="match-score ${m.status === 'IN_PLAY' ? 'live' : ''}">${m.home_score ?? 0} - ${m.away_score ?? 0}</span>`;
  const hf = _flag(m.home_team);
  const af = _flag(m.away_team);

  const countdownHtml = m.status === 'IN_PLAY'
    ? `<div style="text-align:center"><span class="match-inplay-badge">🔴 LIVE</span></div>`
    : (m.status === 'SCHEDULED' && m.utc_date)
      ? `<div style="text-align:center"><span class="match-countdown" data-utc="${m.utc_date}">⏱ …</span></div>`
      : '';

  const metaHtml = m.status !== 'FINISHED' ? `
    <div class="match-meta">
      <span class="status-badge ${statusClass}">${m.status_label}</span>
      ${m.local_time ? ` · ${m.local_time}` : ''}
      ${m.group ? ` · ${m.group}` : ''}
    </div>` : '';

  return `<div class="match-item">
    <div class="match-teams">
      <span class="team home">${hf ? hf + ' ' : ''}${m.home_team}</span>
      ${scoreDisplay}
      <span class="team away">${af ? af + ' ' : ''}${m.away_team}</span>
    </div>
    ${metaHtml}
    ${countdownHtml}
  </div>`;
}
