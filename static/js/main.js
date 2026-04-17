/* ─── Penguinly — main.js ─────────────────────────────────────────────────── */

// ─── Flash auto-dismiss ────────────────────────────────────────────────────────
document.querySelectorAll('.flash').forEach(el => {
  setTimeout(() => {
    el.style.transition = 'opacity 0.4s, transform 0.4s';
    el.style.opacity = '0';
    el.style.transform = 'translateX(20px)';
    setTimeout(() => el.remove(), 400);
  }, 4000);
});

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

// ─── Group chat polling ────────────────────────────────────────────────────────
let lastGroupMsgId = 0;
const chatMessages = document.getElementById('chat-messages');
const groupId = document.body.dataset.groupId;

if (chatMessages && groupId) {
  // Set initial lastId from existing messages
  const msgs = chatMessages.querySelectorAll('[data-msg-id]');
  if (msgs.length) {
    lastGroupMsgId = parseInt(msgs[msgs.length - 1].dataset.msgId, 10) || 0;
  }

  // Scroll to bottom initially
  chatMessages.scrollTop = chatMessages.scrollHeight;

  function appendGroupMessage(msg) {
    const row = document.createElement('div');
    row.className = `message-row${msg.is_own ? ' own' : ''}`;
    row.dataset.msgId = msg.id;

    if (!msg.is_own) {
      row.innerHTML = `
        <div class="avatar avatar-sm message-avatar"
             style="background:${msg.avatar_color}">${msg.initials}</div>
        <div class="message-bubble-wrap">
          <span class="message-sender">${escHtml(msg.display_name)}</span>
          <div class="message-bubble">${escHtml(msg.content)}</div>
          <span class="message-time">${msg.created_at}</span>
        </div>`;
    } else {
      row.innerHTML = `
        <div class="message-bubble-wrap">
          <div class="message-bubble">${escHtml(msg.content)}</div>
          <span class="message-time">${msg.created_at}</span>
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
    } catch (_) { /* network error, retry next tick */ }
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
        <span class="message-time">${msg.created_at}</span>
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
const sidebar = document.querySelector('.sidebar');

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
