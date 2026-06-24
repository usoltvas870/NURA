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

  window.NURA.initUpdateListener = function() {
    if (!('serviceWorker' in navigator)) return;

    navigator.serviceWorker.getRegistration().then(function(reg) {
      if (!reg) return;
      reg.addEventListener('updatefound', function() {
        var newSW = reg.installing;
        if (!newSW) return;
        newSW.addEventListener('statechange', function() {
          if (newSW.state === 'installed' && navigator.serviceWorker.controller) {
            showUpdateToast(newSW);
          }
        });
      });
    });

    var shouldReload = false;
    navigator.serviceWorker.addEventListener('controllerchange', function() {
      if (shouldReload) {
        shouldReload = false;
        window.location.reload();
      }
    });

    function showUpdateToast(newSW) {
      if (document.getElementById('nura-update-toast')) return;
      var toast = document.createElement('div');
      toast.id = 'nura-update-toast';
      toast.setAttribute('role', 'status');
      toast.style.cssText = 'position:fixed;left:16px;right:16px;bottom:calc(var(--tabbar-h,64px) + 12px);z-index:250;background:var(--bg-card);border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--shadow-card-hover);padding:14px 16px;display:flex;align-items:center;gap:12px;max-width:488px;margin:0 auto';
      toast.innerHTML = '<span style="flex:1;font-size:13.5px;color:var(--text)">Доступно обновление NURA</span>' +
        '<button id="nura-update-btn" style="background:var(--terra-d);color:#fff;border:0;border-radius:var(--r-sm);padding:9px 16px;font-size:13px;font-weight:700;cursor:pointer">Обновить</button>';
      document.body.appendChild(toast);
      document.getElementById('nura-update-btn').addEventListener('click', function() {
        shouldReload = true;
        newSW.postMessage({ type: 'SKIP_WAITING' });
      });
    }
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

  /* ── Push Subscribe ────────────────────── */
  function urlBase64ToUint8Array(base64String) {
    var padding = '='.repeat((4 - base64String.length % 4) % 4);
    var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    var rawData = atob(base64);
    var outputArray = new Uint8Array(rawData.length);
    for (var i = 0; i < rawData.length; i++) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  window.NURA.subscribeToPush = function(sessionId) {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      return Promise.reject(new Error('Push not supported'));
    }
    if (localStorage.getItem('nura_push_subscribed') === '1') {
      return Promise.resolve({ already: true });
    }
    return fetch(window.NURA.BASE + '/push/vapid-public-key')
      .then(function(r) { return r.ok ? r.json() : Promise.reject(new Error('VAPID fetch failed')); })
      .then(function(d) {
        if (!d || !d.public_key) throw new Error('No VAPID key');
        return Notification.requestPermission().then(function(permission) {
          if (permission !== 'granted') throw new Error('Notification permission denied');
          return navigator.serviceWorker.ready;
        }).then(function(reg) {
          return reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(d.public_key)
          });
        }).then(function(sub) {
          var keys = sub.toJSON().keys || {};
          return fetch(window.NURA.BASE + '/push/subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              endpoint: sub.endpoint,
              keys: { p256dh: keys.p256dh, auth: keys.auth },
              session_id: sessionId
            })
          }).then(function(r) {
            if (!r.ok) return r.json().then(function(e) { throw new Error((e && e.detail) || 'Subscribe failed'); });
            localStorage.setItem('nura_push_subscribed', '1');
            localStorage.setItem('nura_push_endpoint', sub.endpoint);
            return r.json();
          });
        });
      });
  };

  window.NURA.unsubscribeFromPush = function(sessionId) {
    var endpoint = localStorage.getItem('nura_push_endpoint');
    if (!endpoint) return Promise.resolve();
    return fetch(window.NURA.BASE + '/push/unsubscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint: endpoint, session_id: sessionId })
    }).then(function(r) {
      localStorage.removeItem('nura_push_subscribed');
      localStorage.removeItem('nura_push_endpoint');
      return r.ok ? r.json() : null;
    });
  };

  /* ── Keyboard accessibility ────────────── */
  document.addEventListener('keydown', function(e) {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.getAttribute('role') === 'button') {
      e.preventDefault();
      e.target.click();
    }
  });
})();

if (document.readyState === 'complete') { window.NURA.initUpdateListener(); }
else { window.addEventListener('load', function(){ window.NURA.initUpdateListener(); }); }
