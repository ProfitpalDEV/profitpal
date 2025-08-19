// pp-admin.js — единый мини-утилитник для admin UI (оба экрана)
(() => {
  function applyAdminUI(me) {
    if (!me || !me.is_admin) return;

    // глобальный флаг для admin.css
    document.documentElement.dataset.isAdmin = '1';

    // Бейдж ADMIN MODE (один раз)
    if (!document.getElementById('adminRibbon')) {
      const b = document.createElement('div');
      b.id = 'adminRibbon';
      b.className = 'admin-ribbon';
      b.textContent = 'ADMIN MODE';
      document.body.appendChild(b);
    }

    // Автокорона для отмеченных целей
    document.querySelectorAll('[data-admin-crown], .admin-crown-target').forEach(el => {
      if (el.dataset.crowned) return;
      const span = document.createElement('span');
      span.textContent = '👑';
      span.setAttribute('aria-label', 'Admin');
      span.style.marginLeft = '6px';
      el.appendChild(span);
      el.dataset.crowned = '1';
    });

    // Оформляем шапку (поддерживает и dashboard, и stock-analysis)
    const avatar = document.getElementById('user-avatar') || document.getElementById('userAvatar');
    const greet  = document.getElementById('user-greeting') || document.getElementById('userGreeting');

    if (avatar) {
      avatar.textContent = '👑';
      avatar.style.background = 'linear-gradient(135deg,#ffd700,#ff6b35)';
      avatar.style.border = '3px solid #ffd700';
      avatar.style.boxShadow = '0 0 20px rgba(255,215,0,.6)';
      avatar.style.fontSize = '20px';
    }
    if (greet) {
      greet.innerHTML = '👑 <span style="color:#ffd700;font-size:18px;font-weight:800;">ADMIN MODE</span>';
    }
  }

  function init() {
    if (window.PP_USER) {
      applyAdminUI(window.PP_USER);
      return;
    }
    // подстраховка: достанем сессию сами, если не успела установиться
    fetch('/api/session/me', { credentials: 'include' })
      .then(r => (r.ok ? r.json() : null))
      .then(me => {
        if (me && me.is_admin) {
          window.PP_USER = window.PP_USER || me;
          applyAdminUI(me);
        }
      })
      .catch(() => {});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
