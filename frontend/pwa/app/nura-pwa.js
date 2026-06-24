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

    navigator.serviceWorker.ready.then(function(reg) {
      if (reg.waiting) {
        showUpdateToast(reg.waiting);
      }

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

      var backdrop = document.createElement('div');
      backdrop.id = 'nura-update-toast';
      backdrop.style.cssText = 'position:fixed;inset:0;z-index:249;background:rgba(0,0,0,.45);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;padding:24px';

      var card = document.createElement('div');
      card.style.cssText = 'width:min(100%,360px);background:#1A1814;border-radius:20px;padding:28px 24px 20px;box-shadow:0 24px 64px rgba(0,0,0,.55);text-align:center';

      card.innerHTML =
        '<div style="width:52px;height:52px;border-radius:50%;background:rgba(255,255,255,.08);display:grid;place-items:center;margin:0 auto 16px;font-size:24px">✦</div>' +
        '<div style="font-family:var(--font-serif);font-size:22px;color:#fff;margin-bottom:8px">Новая версия NURA</div>' +
        '<div style="font-size:13px;color:rgba(255,255,255,.55);line-height:1.5;margin-bottom:24px">Обновление готово — нажми чтобы применить</div>' +
        '<button id="nura-update-btn" style="display:block;width:100%;min-height:50px;background:#fff;color:#12100E;border:0;border-radius:12px;font-size:15px;font-weight:800;cursor:pointer;letter-spacing:.01em;-webkit-tap-highlight-color:transparent;transition:opacity .15s,transform .15s">Обновить сейчас</button>' +
        '<button id="nura-update-skip" style="display:block;width:100%;min-height:44px;background:transparent;color:rgba(255,255,255,.40);border:0;border-radius:12px;font-size:13px;font-weight:600;cursor:pointer;margin-top:4px;-webkit-tap-highlight-color:transparent">Позже</button>';

      backdrop.appendChild(card);
      document.body.appendChild(backdrop);

      var btn = document.getElementById('nura-update-btn');
      btn.addEventListener('touchstart', function() { btn.style.opacity='.75'; btn.style.transform='scale(.97)'; }, {passive:true});
      btn.addEventListener('touchend', function() { btn.style.opacity=''; btn.style.transform=''; });
      btn.addEventListener('click', function() {
        btn.textContent = 'Обновляю…';
        btn.disabled = true;
        shouldReload = true;
        newSW.postMessage({ type: 'SKIP_WAITING' });
      });

      document.getElementById('nura-update-skip').addEventListener('click', function() {
        backdrop.remove();
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
