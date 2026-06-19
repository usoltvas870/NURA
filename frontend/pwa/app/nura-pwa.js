/* NURA PWA — Shared JS */
(function() {
  'use strict';

  /* ── Theme ─────────────────────────────── */
  window.NURA = window.NURA || {};

  window.NURA.applyTheme = function(theme) {
    document.documentElement.setAttribute('data-theme', theme);
  };

  window.NURA.toggleTheme = function() {
    var current = document.documentElement.getAttribute('data-theme') || 'light';
    var next = current === 'dark' ? 'light' : 'dark';
    window.NURA.applyTheme(next);
    localStorage.setItem('nura-theme', next);
    return next;
  };

  /* ── API ───────────────────────────────── */
  window.NURA.BASE = 'https://nura-ai.ru/api/v1';
  window.NURA.sessionId = localStorage.getItem('nura_session_id');

  window.NURA.fetchJSON = function(url, options) {
    options = options || {};
    return fetch(url, options)
      .then(function(r) { return r.ok ? r.json() : null; });
  };

  /* ── Helpers ────────────────────────────── */
  window.NURA.escHtml = function(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
  };

  window.NURA.now = function() {
    var d = new Date();
    return d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0');
  };
})();
