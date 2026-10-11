// AutoQA UI Helpers & Theme Controller
(function() {
  'use strict';

  // 1. Theme Controller with system preference & localStorage
  var THEME_KEY = 'autoqa_theme';

  function getSavedTheme() {
    try {
      return localStorage.getItem(THEME_KEY);
    } catch (e) {
      return null;
    }
  }

  function saveTheme(theme) {
    try {
      if (theme) {
        localStorage.setItem(THEME_KEY, theme);
      } else {
        localStorage.removeItem(THEME_KEY);
      }
    } catch (e) {
      console.warn('localStorage access failed:', e);
    }
  }

  function applyTheme(theme) {
    var root = document.documentElement;
    if (theme === 'dark') {
      root.setAttribute('data-theme', 'dark');
    } else if (theme === 'light') {
      root.setAttribute('data-theme', 'light');
    } else {
      root.removeAttribute('data-theme');
    }
    updateThemeButtons(theme || 'system');
  }

  function updateThemeButtons(current) {
    var toggles = document.querySelectorAll('[data-theme-toggle]');
    toggles.forEach(function(btn) {
      var isDark = current === 'dark' || (current === 'system' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
      btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
      btn.setAttribute('aria-label', isDark ? 'Switch to light theme' : 'Switch to dark theme');
      var icon = btn.querySelector('.theme-icon');
      if (icon) {
        icon.innerHTML = isDark 
          ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>'
          : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
      }
    });
  }

  // Apply saved theme early to prevent flash
  var initialTheme = getSavedTheme();
  if (initialTheme) {
    applyTheme(initialTheme);
  }

  document.addEventListener('DOMContentLoaded', function() {
    updateThemeButtons(getSavedTheme() || 'system');

    // Theme toggle click handler
    document.addEventListener('click', function(e) {
      var toggle = e.target.closest('[data-theme-toggle]');
      if (!toggle) return;
      
      var currentAttr = document.documentElement.getAttribute('data-theme');
      var nextTheme;
      if (!currentAttr) {
        var systemDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        nextTheme = systemDark ? 'light' : 'dark';
      } else if (currentAttr === 'dark') {
        nextTheme = 'light';
      } else {
        nextTheme = 'dark';
      }
      saveTheme(nextTheme);
      applyTheme(nextTheme);
    });

    // Listen to OS preference changes if no manual theme chosen
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
        if (!getSavedTheme()) {
          updateThemeButtons('system');
        }
      });
    }

    // 2. Micro-interactions: Instant press feedback (Spring feel)
    document.querySelectorAll('.btn, button, .navbar a').forEach(function(el) {
      el.addEventListener('pointerdown', function() {
        el.classList.add('is-active-pressed');
      });
      el.addEventListener('pointerup', function() {
        el.classList.remove('is-active-pressed');
      });
      el.addEventListener('pointerleave', function() {
        el.classList.remove('is-active-pressed');
      });
    });

    // 3. Screenshot Modal & Keyboard handling
    var modal = document.getElementById('screenshot-modal');
    if (modal) {
      var modalImg = modal.querySelector('img');

      function openModal(src, alt) {
        if (!modalImg) return;
        modalImg.src = src;
        modalImg.alt = alt || 'Screenshot preview';
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
      }

      function closeModal() {
        modal.classList.remove('active');
        document.body.style.overflow = '';
      }

      document.addEventListener('click', function(e) {
        var thumb = e.target.closest('[data-screenshot-src]');
        if (thumb) {
          openModal(thumb.getAttribute('data-screenshot-src'), thumb.getAttribute('data-screenshot-alt'));
          return;
        }
        if (e.target === modal || e.target.closest('.modal-close')) {
          closeModal();
        }
      });

      document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal.classList.contains('active')) {
          closeModal();
        }
      });
    }

    // 4. Copy to clipboard helpers with visual feedback
    document.querySelectorAll('[data-copy-target]').forEach(function(btn) {
      btn.addEventListener('click', async function() {
        var targetId = btn.getAttribute('data-copy-target');
        var targetEl = document.getElementById(targetId);
        if (!targetEl) return;
        var text = targetEl.value || targetEl.innerText;
        try {
          await navigator.clipboard.writeText(text);
          var originalText = btn.innerHTML;
          btn.innerHTML = '<span>✓ Copied</span>';
          btn.classList.add('btn-copied');
          setTimeout(function() {
            btn.innerHTML = originalText;
            btn.classList.remove('btn-copied');
          }, 2000);
        } catch (err) {
          console.error('Failed to copy:', err);
        }
      });
    });
  });
})();
