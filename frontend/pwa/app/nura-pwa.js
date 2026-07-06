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
        '<div style="width:52px;height:52px;border-radius:50%;background:rgba(184,116,63,.22);display:grid;place-items:center;margin:0 auto 16px;font-size:24px;color:#B8743F">✦</div>' +
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
  window.NURA.BASE = (location.origin === 'https://nura-ai.ru') ? 'https://nura-ai.ru/api/v1' : '/api/v1';

  window.NURA.fetchJSON = function(url, options) {
    options = options || {};
    if (!options.credentials) options.credentials = 'same-origin';
    return fetch(url, options)
      .then(function(r) {
        if (r.ok) return r.json();
        var err = new Error('HTTP ' + r.status);
        err.status = r.status;
        throw err;
      });
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

  window.NURA.subscribeToPush = function() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      return Promise.reject(new Error('Push not supported'));
    }
    if (localStorage.getItem('nura_push_subscribed') === '1') {
      return Promise.resolve({ already: true });
    }
    return fetch(window.NURA.BASE + '/push/vapid-public-key', {credentials:'same-origin'})
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
            credentials: 'same-origin',
            body: JSON.stringify({
              endpoint: sub.endpoint,
              keys: { p256dh: keys.p256dh, auth: keys.auth }
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

  window.NURA.unsubscribeFromPush = function() {
    var endpoint = localStorage.getItem('nura_push_endpoint');
    if (!endpoint) return Promise.resolve();
    return fetch(window.NURA.BASE + '/push/unsubscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ endpoint: endpoint })
    }).then(function(r) {
      localStorage.removeItem('nura_push_subscribed');
      localStorage.removeItem('nura_push_endpoint');
      return r.ok ? r.json() : null;
    });
  };

  window.NURA.ensureVKSDK = function() {
    if (window.VKIDSDK) return Promise.resolve(window.VKIDSDK);
    if (window.NURA._vkSdkPromise) return window.NURA._vkSdkPromise;

    window.NURA._vkSdkPromise = new Promise(function(resolve, reject) {
      var script = document.getElementById('nura-vk-sdk');
      function cleanup() {
        if (!script) return;
        script.removeEventListener('load', onLoad);
        script.removeEventListener('error', onError);
      }
      function onLoad() {
        cleanup();
        if (window.VKIDSDK) resolve(window.VKIDSDK);
        else reject(new Error('VK SDK unavailable'));
      }
      function onError() {
        cleanup();
        window.NURA._vkSdkPromise = null;
        reject(new Error('VK SDK load failed'));
      }

      if (!script) {
        script = document.createElement('script');
        script.id = 'nura-vk-sdk';
        script.src = '/assets/vendor/vkid-sdk.js';
        script.async = true;
        document.head.appendChild(script);
      }

      if (window.VKIDSDK) {
        cleanup();
        resolve(window.VKIDSDK);
        return;
      }

      script.addEventListener('load', onLoad);
      script.addEventListener('error', onError);
    });

    return window.NURA._vkSdkPromise;
  };

  window.NURA.showAuthModal = function(options) {
    options = options || {};
    if (document.getElementById('nura-auth-modal')) return;

    var title = options.title || 'Войди в NURA';
    var copy = options.copy || 'Создай аккаунт, чтобы открыть карту дня, чат и персональные экраны приложения.';
    var extraLink = options.extraLink || null;
    var extraLinkLabel = options.extraLinkLabel || 'Пройти бесплатный мини-разбор';
    var backdrop = document.createElement('div');
    backdrop.id = 'nura-auth-modal';
    backdrop.style.cssText = 'position:fixed;inset:0;z-index:400;background:rgba(0,0,0,.55);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;padding:24px';

    var card = document.createElement('div');
    card.style.cssText = 'width:min(100%,400px);background:var(--bg-card);border-radius:var(--r-xl);padding:28px 22px 22px;box-shadow:0 20px 60px rgba(0,0,0,.28);position:relative;max-height:90vh;overflow-y:auto';

    var extraLinkHtml = '';
    if (extraLink) {
      extraLinkHtml = '<div style="text-align:center;margin-top:18px;padding-top:18px;border-top:1px solid var(--line)">' +
        '<a href="' + extraLink + '" style="font-size:13px;color:var(--terra);font-weight:800;text-decoration:none">' + window.NURA.escHtml(extraLinkLabel) + ' →</a>' +
        '<div style="font-size:11px;color:var(--text-s);margin-top:4px">Без регистрации — получи первый разбор</div>' +
        '</div>';
    }

    card.innerHTML =
      '<button id="auth-modal-close" aria-label="Закрыть" style="position:absolute;top:12px;right:12px;width:32px;height:32px;border-radius:50%;border:1px solid var(--line);background:var(--bg-card-soft);color:var(--text-m);font-size:16px;cursor:pointer;display:grid;place-items:center">&times;</button>' +
      '<div style="text-align:center;margin-bottom:20px">' +
        '<div style="width:56px;height:56px;border-radius:50%;background:rgba(184,116,63,.12);color:var(--terra);display:grid;place-items:center;font-size:28px;margin:0 auto 16px">✦</div>' +
        '<h3 style="font-family:var(--font-serif);font-size:24px;color:var(--text);margin-bottom:8px;font-weight:400">' + window.NURA.escHtml(title) + '</h3>' +
        '<p style="font-size:13.5px;color:var(--text-m);line-height:1.5">' + window.NURA.escHtml(copy) + '</p>' +
      '</div>' +
      '<div style="display:grid;gap:10px">' +
        '<button class="btn btn-primary btn-full" id="auth-email-btn" type="button" style="min-height:50px"><span class="btn-text">Продолжить через Email</span><span class="loader"></span></button>' +
        '<div style="font-size:11px;color:var(--text-s);text-align:center;margin-top:-2px">Без пароля — вход по ссылке</div>' +
        '<div id="auth-email-form" style="display:none;grid-template-columns:1fr;gap:10px">' +
          '<input class="input" type="email" id="auth-email-input" placeholder="you@example.com" autocomplete="email" style="height:48px">' +
          '<button class="btn btn-soft btn-full" id="auth-email-submit" type="button" style="min-height:48px"><span class="btn-text">Отправить ссылку</span><span class="loader"></span></button>' +
        '</div>' +
        '<div id="auth-success" style="display:none;text-align:center;padding:8px 0"></div>' +
        '<div id="auth-error" style="display:none;color:var(--danger);font-size:12px;text-align:center;margin-top:4px"></div>' +
        '<div style="display:flex;align-items:center;gap:12px;margin:8px 0">' +
          '<div style="flex:1;height:1px;background:var(--line)"></div>' +
          '<span style="font-size:11px;color:var(--text-s)">или</span>' +
          '<div style="flex:1;height:1px;background:var(--line)"></div>' +
        '</div>' +
        '<button class="btn btn-vk btn-full" id="auth-vk-btn" type="button" style="min-height:50px;background:#0077FF;color:#fff;gap:10px">' +
          '<svg style="width:20px;height:20px;flex-shrink:0" viewBox="0 0 24 24" fill="currentColor"><path d="M13.16 17.5c-5.46 0-9.13-3.74-9.29-9.96h2.76c.11 4.57 2.32 6.49 4.05 6.89V7.54h2.61v3.96c1.71-.18 3.5-1.95 4.1-3.96h2.58c-.43 2.43-2.36 4.2-3.71 4.93 1.35.6 3.56 2.14 4.4 4.93h-2.86c-.65-2.03-2.27-3.6-4.51-3.81v3.81h-.31z"/></svg>' +
          '<span>Войти через VK</span>' +
        '</button>' +
      '</div>' +
      extraLinkHtml;

    backdrop.appendChild(card);
    document.body.appendChild(backdrop);

    function closeModal() {
      backdrop.remove();
    }

    document.getElementById('auth-modal-close').addEventListener('click', closeModal);
    backdrop.addEventListener('click', function(e) {
      if (e.target === backdrop) closeModal();
    });

    var emailForm = document.getElementById('auth-email-form');
    var emailSuccess = document.getElementById('auth-success');
    var emailError = document.getElementById('auth-error');
    var emailBtn = document.getElementById('auth-email-btn');
    var emailSubmit = document.getElementById('auth-email-submit');

    emailBtn.addEventListener('click', function() {
      emailError.style.display = 'none';
      if (emailForm.style.display === 'grid') {
        emailForm.style.display = 'none';
        return;
      }
      emailSuccess.style.display = 'none';
      emailForm.style.display = 'grid';
      document.getElementById('auth-email-input').focus();
    });

    emailSubmit.addEventListener('click', function() {
      var btn = this;
      var email = document.getElementById('auth-email-input').value.trim();
      emailError.style.display = 'none';
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        emailError.textContent = 'Проверь адрес почты';
        emailError.style.display = 'block';
        return;
      }
      btn.classList.add('loading');
      btn.disabled = true;
      fetch(window.NURA.BASE + '/auth/email/send', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({
          email: email,
          guest_token: localStorage.getItem('nura_guest_token') || undefined
        })
      })
      .then(function(r) {
        if (!r.ok) throw new Error('send error');
        return r.json();
      })
      .then(function() {
        btn.classList.remove('loading');
        btn.disabled = false;
        emailForm.style.display = 'none';
        emailSuccess.style.display = 'block';
        emailSuccess.innerHTML = '<p style="font-size:14px;color:var(--text-m);line-height:1.5;margin-bottom:12px">Письмо отправлено. Проверь почту — там ссылка для входа.</p>';
      })
      .catch(function() {
        btn.classList.remove('loading');
        btn.disabled = false;
        emailError.textContent = 'Не удалось отправить письмо. Попробуй ещё раз';
        emailError.style.display = 'block';
      });
    });

    document.getElementById('auth-vk-btn').addEventListener('click', function() {
      var btn = this;
      btn.disabled = true;
      emailError.style.display = 'none';

      window.NURA.ensureVKSDK()
        .then(function(SDK) {
          var bytes = new Uint8Array(32);
          crypto.getRandomValues(bytes);
          var binary = '';
          var i;
          for (i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
          var state = btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');

          bytes = new Uint8Array(64);
          crypto.getRandomValues(bytes);
          binary = '';
          for (i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
          var codeVerifier = btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');

          sessionStorage.setItem('nura_vk_state', state);
          sessionStorage.setItem('nura_vk_code_verifier', codeVerifier);
          sessionStorage.setItem('nura_vk_started_at', String(Date.now()));
          SDK.Config.init({
            app: 54660807,
            redirectUrl: 'https://nura-ai.ru/vk-callback.html',
            state: state,
            codeVerifier: codeVerifier,
            scope: 'email'
          });
          return SDK.Auth.login();
        })
        .catch(function() {
          emailError.textContent = 'Не удалось открыть вход через VK.';
          emailError.style.display = 'block';
        })
        .finally(function() {
          btn.disabled = false;
        });
    });
  };

  window.NURA.requireAuth = function(isGuest, options) {
    if (!isGuest) return false;
    window.NURA.showAuthModal(options);
    return true;
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
