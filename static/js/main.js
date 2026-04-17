/* ─── Penguinly — main.js ─────────────────────────────────────────────────── */

// ─── Theme init (runs ASAP via inline script in base.html, but also here as fallback)
(function () {
  var t = localStorage.getItem('theme') || 'sunset';
  document.documentElement.setAttribute('data-theme', t);
})();

// ─── Flash auto-dismiss ────────────────────────────────────────────────────────
document.querySelectorAll('.flash').forEach(el => {
  setTimeout(() => {
    el.style.transition = 'opacity 0.4s, transform 0.4s';
    el.style.opacity = '0';
    el.style.transform = 'translateX(20px)';
    setTimeout(() => el.remove(), 400);
  }, 4000);
});

// ─── Sidebar collapse ─────────────────────────────────────────────────────────
const sidebar = document.querySelector('.sidebar');
const collapseBtn = document.getElementById('sidebar-collapse-btn');

if (sidebar) {
  // Restore saved state
  if (localStorage.getItem('sidebarCollapsed') === '1') {
    sidebar.classList.add('collapsed');
  }

  if (collapseBtn) {
    collapseBtn.addEventListener('click', () => {
      sidebar.classList.toggle('collapsed');
      localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed') ? '1' : '0');
    });
  }
}

// ─── Theme switcher (settings page) ──────────────────────────────────────────
document.querySelectorAll('.theme-option').forEach(opt => {
  opt.addEventListener('click', () => {
    const theme = opt.dataset.theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    // Update radio/active state
    document.querySelectorAll('.theme-option').forEach(o => o.classList.remove('active'));
    opt.classList.add('active');
    // Sync hidden input if present
    const input = document.getElementById('theme-input');
    if (input) input.value = theme;
  });
});

// Mark current theme option as active on settings page load
(function () {
  const current = document.documentElement.getAttribute('data-theme') || 'sunset';
  const opt = document.querySelector(`.theme-option[data-theme="${current}"]`);
  if (opt) opt.classList.add('active');
  const input = document.getElementById('theme-input');
  if (input) input.value = current;
})();

// ─── Article mode toggle ──────────────────────────────────────────────────────
const articleToggle = document.getElementById('article-mode-toggle');
if (articleToggle) {
  articleToggle.addEventListener('change', () => {
    const input = document.getElementById('article-mode-input');
    if (input) input.value = articleToggle.checked ? '1' : '0';
  });
}

// ─── EasyMDE init for article mode compose ────────────────────────────────────
const mdTextarea = document.getElementById('md-editor');
if (mdTextarea && typeof EasyMDE !== 'undefined') {
  const easyMDE = new EasyMDE({
    element: mdTextarea,
    autofocus: false,
    spellChecker: false,
    placeholder: 'Write your article… supports **bold**, *italic*, `code`, > quotes, ==highlight==',
    toolbar: [
      'bold', 'italic', 'strikethrough', '|',
      'heading-1', 'heading-2', 'heading-3', '|',
      'quote', 'code', 'table', '|',
      'unordered-list', 'ordered-list', '|',
      'link', '|',
      'preview', 'side-by-side', 'fullscreen',
    ],
    status: false,
    minHeight: '200px',
  });
}

// ─── Character counter for compose/post textarea ──────────────────────────────
const composeArea = document.getElementById('compose-textarea');
const charCounter = document.getElementById('char-counter');
const MAX_CHARS = 500;

if (composeArea && charCounter) {
  composeArea.addEventListener('input', () => {
    const len = composeArea.value.length;
    charCounter.textContent = `${len} / ${MAX_CHARS}`;
    charCounter.className = 'char-counter';
    if (len > MAX_CHARS * 0.85) charCounter.classList.add('warn');
    if (len > MAX_CHARS) charCounter.classList.add('over');
  });
}

// ─── Comment toggle ────────────────────────────────────────────────────────────
document.querySelectorAll('.comment-toggle-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const postId = btn.dataset.postId;
    const section = document.getElementById(`comments-${postId}`);
    if (section) {
      section.classList.toggle('open');
      const isOpen = section.classList.contains('open');
      btn.setAttribute('aria-expanded', isOpen);
    }
  });
});

// ─── Inline comment edit ──────────────────────────────────────────────────────
document.querySelectorAll('.comment-edit-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const commentId = btn.dataset.commentId;
    const textEl = document.getElementById(`comment-text-${commentId}`);
    const formEl = document.getElementById(`comment-edit-form-${commentId}`);
    if (textEl && formEl) {
      textEl.style.display = 'none';
      formEl.style.display = 'flex';
      const ta = formEl.querySelector('textarea');
      if (ta) { ta.focus(); ta.selectionStart = ta.selectionEnd = ta.value.length; }
    }
  });
});

document.querySelectorAll('.comment-edit-cancel').forEach(btn => {
  btn.addEventListener('click', () => {
    const commentId = btn.dataset.commentId;
    const textEl = document.getElementById(`comment-text-${commentId}`);
    const formEl = document.getElementById(`comment-edit-form-${commentId}`);
    if (textEl && formEl) {
      textEl.style.display = '';
      formEl.style.display = 'none';
    }
  });
});

// ─── Group chat polling ────────────────────────────────────────────────────────
let lastGroupMsgId = 0;
const chatMessages = document.getElementById('chat-messages');
const groupId = document.body.dataset.groupId;

if (chatMessages && groupId) {
  const msgs = chatMessages.querySelectorAll('[data-msg-id]');
  if (msgs.length) {
    lastGroupMsgId = parseInt(msgs[msgs.length - 1].dataset.msgId, 10) || 0;
  }

  chatMessages.scrollTop = chatMessages.scrollHeight;

  function appendGroupMessage(msg) {
    const row = document.createElement('div');
    row.className = `message-row${msg.is_own ? ' own' : ''}`;
    row.dataset.msgId = msg.id;

    if (!msg.is_own) {
      row.innerHTML = `
        <div class="avatar avatar-sm message-avatar"
             style="background:${msg.avatar_color}">${escHtml(msg.initials)}</div>
        <div class="message-bubble-wrap">
          <span class="message-sender">${escHtml(msg.display_name)}</span>
          <div class="message-bubble">${escHtml(msg.content)}</div>
          <span class="message-time">${escHtml(msg.created_at)}</span>
        </div>`;
    } else {
      row.innerHTML = `
        <div class="message-bubble-wrap">
          <div class="message-bubble">${escHtml(msg.content)}</div>
          <span class="message-time">${escHtml(msg.created_at)}</span>
        </div>`;
    }

    chatMessages.appendChild(row);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  async function pollGroupMessages() {
    try {
      const res = await fetch(`/api/groups/${groupId}/messages?after=${lastGroupMsgId}`);
      if (!res.ok) return;
      const data = await res.json();
      data.forEach(msg => {
        appendGroupMessage(msg);
        if (msg.id > lastGroupMsgId) lastGroupMsgId = msg.id;
      });
    } catch (_) {}
  }

  setInterval(pollGroupMessages, 2500);
}

// ─── DM chat polling ──────────────────────────────────────────────────────────
let lastDmMsgId = 0;
const dmMessages = document.getElementById('dm-messages');
const dmUserId = document.body.dataset.dmUserId;

if (dmMessages && dmUserId) {
  const msgs = dmMessages.querySelectorAll('[data-msg-id]');
  if (msgs.length) {
    lastDmMsgId = parseInt(msgs[msgs.length - 1].dataset.msgId, 10) || 0;
  }
  dmMessages.scrollTop = dmMessages.scrollHeight;

  function appendDmMessage(msg) {
    const bubble = document.createElement('div');
    bubble.className = `message-row${msg.is_own ? ' own' : ''}`;
    bubble.dataset.msgId = msg.id;
    bubble.innerHTML = `
      <div class="message-bubble-wrap">
        <div class="message-bubble">${escHtml(msg.content)}</div>
        <span class="message-time">${escHtml(msg.created_at)}</span>
      </div>`;
    dmMessages.appendChild(bubble);
    dmMessages.scrollTop = dmMessages.scrollHeight;
  }

  async function pollDmMessages() {
    try {
      const res = await fetch(`/api/dm/${dmUserId}/messages?after=${lastDmMsgId}`);
      if (!res.ok) return;
      const data = await res.json();
      data.forEach(msg => {
        appendDmMessage(msg);
        if (msg.id > lastDmMsgId) lastDmMsgId = msg.id;
      });
    } catch (_) {}
  }

  setInterval(pollDmMessages, 2000);
}

// ─── Badge count polling ──────────────────────────────────────────────────────
const notifBadge = document.getElementById('notif-badge');
const dmBadge = document.getElementById('dm-badge');
const inviteBadge = document.getElementById('invite-badge');

if (notifBadge || dmBadge) {
  async function pollBadges() {
    try {
      const res = await fetch('/api/badge-counts');
      if (!res.ok) return;
      const data = await res.json();
      updateBadge(notifBadge, data.notifications);
      updateBadge(dmBadge, data.dms);
      updateBadge(inviteBadge, data.invites);
    } catch (_) {}
  }

  function updateBadge(el, count) {
    if (!el) return;
    if (count > 0) {
      el.textContent = count;
      el.style.display = 'flex';
    } else {
      el.style.display = 'none';
    }
  }

  setInterval(pollBadges, 15000);
}

// ─── Invite user select → search filter ──────────────────────────────────────
const inviteSearch = document.getElementById('invite-search');
const inviteSelect = document.getElementById('invite-select');

if (inviteSearch && inviteSelect) {
  inviteSearch.addEventListener('input', () => {
    const q = inviteSearch.value.toLowerCase();
    Array.from(inviteSelect.options).forEach(opt => {
      const match = opt.text.toLowerCase().includes(q);
      opt.style.display = match ? '' : 'none';
    });
  });
}

// ─── Avatar color picker preview ──────────────────────────────────────────────
const colorPicker = document.getElementById('avatar-color-picker');
const colorPreview = document.getElementById('avatar-color-preview');

if (colorPicker && colorPreview) {
  colorPicker.addEventListener('input', () => {
    colorPreview.style.background = colorPicker.value;
  });
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ─── Auto-grow textareas ──────────────────────────────────────────────────────
document.querySelectorAll('textarea[data-autogrow]').forEach(ta => {
  ta.addEventListener('input', () => {
    ta.style.height = 'auto';
    ta.style.height = ta.scrollHeight + 'px';
  });
});

// ─── Mobile sidebar toggle ────────────────────────────────────────────────────
const mobileMenuBtn = document.getElementById('mobile-menu-btn');

if (mobileMenuBtn && sidebar) {
  mobileMenuBtn.addEventListener('click', () => {
    sidebar.classList.toggle('mobile-open');
  });
  document.addEventListener('click', e => {
    if (!sidebar.contains(e.target) && !mobileMenuBtn.contains(e.target)) {
      sidebar.classList.remove('mobile-open');
    }
  });
}

// ─── Image upload preview ─────────────────────────────────────────────────────
const imageInput = document.getElementById('post-image-input');
const imagePreview = document.getElementById('post-image-preview');
const imagePreviewImg = document.getElementById('post-image-preview-img');
const imageRemoveBtn = document.getElementById('post-image-remove');

if (imageInput && imagePreview && imagePreviewImg) {
  imageInput.addEventListener('change', () => {
    const file = imageInput.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = e => {
        imagePreviewImg.src = e.target.result;
        imagePreview.style.display = 'block';
      };
      reader.readAsDataURL(file);
    }
  });

  if (imageRemoveBtn) {
    imageRemoveBtn.addEventListener('click', () => {
      imageInput.value = '';
      imagePreview.style.display = 'none';
      imagePreviewImg.src = '';
    });
  }
}
