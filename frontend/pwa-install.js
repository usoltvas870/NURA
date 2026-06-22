// NURA PWA Install UI v2
// Adaptive install guidance based on browser capabilities

(function () {
  'use strict';

  function isIOS(ua) {
    ua = ua || navigator.userAgent;
    return /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
  }

  function isPWAInstalled() {
    return window.matchMedia('(display-mode: standalone)').matches
      || window.navigator.standalone === true;
  }

  function getIOSVersion() {
    var m = navigator.userAgent.match(/OS (\d+)_/);
    return m ? parseInt(m[1], 10) : 0;
  }

  /**
   * Returns the install scenario for the current browser.
   * Accepts optional mock navigator for testability.
   *
   * @param {object} [nav] — mock object with .userAgent, .userAgentData.brands, .standalone
   * @returns {'installed'|'ios'|'opera'|'chromium'|'unknown'}
   */
  function detectScenario(nav) {
    nav = nav || navigator;

    if (nav.standalone === true) return 'installed';
    if (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) return 'installed';

    var ua = nav.userAgent || '';

    if (/iPad|iPhone|iPod/.test(ua) && !window.MSStream) return 'ios';

    if (ua.indexOf('OPR') !== -1 || ua.indexOf('Opera') !== -1) return 'opera';

    if (nav.userAgentData && nav.userAgentData.brands) {
      var brands = nav.userAgentData.brands;
      for (var i = 0; i < brands.length; i++) {
        var b = brands[i].brand;
        if (b === 'Google Chrome' || b === 'Microsoft Edge'
          || b === 'Chromium' || b === 'Brave') {
          return 'chromium';
        }
      }
    }

    if (/Chrome|Chromium|Edg\//.test(ua)) return 'chromium';

    return 'unknown';
  }

  var _deferredPrompt = null;
  var _currentScenario = null;

  // --- Banner DOM builder ---

  function buildBannerHTML(scenario) {
    if (scenario === 'chromium') {
      return '<div style="flex:1">'
        + '<div style="font-weight:800;font-size:14px;color:var(--text)">Установи NURA</div>'
        + '<div style="font-size:12px;color:var(--text-m);margin-top:2px">Быстрый доступ без браузера</div>'
        + '</div>'
        + '<button id="pwa-install-btn" style="background:var(--terra);color:#fff;border:0;border-radius:var(--r-sm);padding:10px 18px;font-size:13px;font-weight:800;cursor:pointer;flex-shrink:0;white-space:nowrap">Установить</button>'
        + '<button id="pwa-banner-close" title="Скрыть" style="width:32px;height:32px;border-radius:50%;border:1px solid var(--line);background:var(--bg-card-soft);color:var(--text-m);font-size:16px;cursor:pointer;flex-shrink:0;display:grid;place-items:center">✕</button>';
    }

    if (scenario === 'opera') {
      return '<div style="flex:1">'
        + '<div style="font-weight:800;font-size:14px;color:var(--text);line-height:1.2">Добавь NURA на главный экран</div>'
        + '<div style="font-size:12px;color:var(--text-m);margin-top:4px;display:flex;align-items:center;gap:6px">'
        + '<span style="display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:4px;background:rgba(184,116,63,.12);color:var(--terra);font-size:13px;font-weight:800;flex-shrink:0">⋮</span>'
        + 'Меню → Добавить на главный экран</div>'
        + '</div>'
        + '<button id="pwa-banner-close" title="Скрыть" style="width:32px;height:32px;border-radius:50%;border:1px solid var(--line);background:var(--bg-card-soft);color:var(--text-m);font-size:16px;cursor:pointer;flex-shrink:0;display:grid;place-items:center">✕</button>';
    }

    // unknown — generic manual instruction
    return '<div style="flex:1">'
      + '<div style="font-weight:800;font-size:14px;color:var(--text);line-height:1.2">Добавь NURA на главный экран</div>'
      + '<div style="font-size:12px;color:var(--text-m);margin-top:4px">Меню браузера → «Добавить на главный экран» или «Установить приложение»</div>'
      + '</div>'
      + '<button id="pwa-banner-close" title="Скрыть" style="width:32px;height:32px;border-radius:50%;border:1px solid var(--line);background:var(--bg-card-soft);color:var(--text-m);font-size:16px;cursor:pointer;flex-shrink:0;display:grid;place-items:center">✕</button>';
  }

  function populateBanner(scenario) {
    var banner = document.getElementById('pwa-install-banner');
    if (!banner) return;
    banner.innerHTML = buildBannerHTML(scenario);
  }

  // --- Banner show / hide ---

  function showInstallBanner() {
    if (isPWAInstalled()) return;
    if (sessionStorage.getItem('install_banner_dismissed')) return;

    var banner = document.getElementById('pwa-install-banner');
    if (!banner) return;

    banner.style.display = 'flex';

    var closeBtn = document.getElementById('pwa-banner-close');
    if (closeBtn) closeBtn.onclick = dismissInstallBanner;

    var installBtn = document.getElementById('pwa-install-btn');
    if (installBtn) installBtn.onclick = triggerInstall;
  }

  function hideInstallBanner() {
    var banner = document.getElementById('pwa-install-banner');
    if (banner) banner.style.display = 'none';
  }

  function dismissInstallBanner() {
    sessionStorage.setItem('install_banner_dismissed', '1');
    hideInstallBanner();
  }

  function triggerInstall() {
    if (!_deferredPrompt) return false;

    _deferredPrompt.prompt();

    _deferredPrompt.userChoice.then(function (choice) {
      _deferredPrompt = null;
      if (choice.outcome === 'accepted') {
        hideInstallBanner();
        if (typeof ym !== 'undefined' && window._YM_ID) {
          ym(window._YM_ID, 'reachGoal', 'pwa_installed');
        }
      }
    });

    return true;
  }

  // --- iOS modal (unchanged flow) ---

  function showIOSInstallModal() {
    var modal = document.getElementById('pwa-ios-modal');
    if (modal) modal.style.display = 'flex';
  }

  function hideIOSInstallModal() {
    var modal = document.getElementById('pwa-ios-modal');
    if (modal) modal.style.display = 'none';
    sessionStorage.setItem('ios_install_shown', '1');
  }

  // --- Init ---

  function initPWAInstall() {
    _currentScenario = detectScenario();

    if (_currentScenario === 'installed') return;

    if (_currentScenario === 'ios') {
      if (getIOSVersion() >= 15 && !sessionStorage.getItem('ios_install_shown')) {
        setTimeout(function () { showIOSInstallModal(); }, 4000);
      }
      return;
    }

    populateBanner(_currentScenario);

    if (_currentScenario === 'opera' || _currentScenario === 'unknown') {
      setTimeout(function () { showInstallBanner(); }, 2500);
    }
  }

  // --- Event listeners ---

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    _deferredPrompt = e;

    if (_currentScenario === 'chromium') {
      showInstallBanner();
    }
  });

  window.addEventListener('appinstalled', function () {
    _deferredPrompt = null;
    hideInstallBanner();
    if (typeof ym !== 'undefined' && window._YM_ID) {
      ym(window._YM_ID, 'reachGoal', 'pwa_installed');
    }
  });

  // --- Boot ---

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPWAInstall);
  } else {
    initPWAInstall();
  }

  // --- Public API (backward compatible) ---

  window.NURA_PWA = {
    detectScenario: detectScenario,
    showInstallBanner: showInstallBanner,
    hideInstallBanner: hideInstallBanner,
    dismissInstallBanner: dismissInstallBanner,
    triggerInstall: triggerInstall,
    triggerAndroidInstall: triggerInstall,
    showIOSInstallModal: showIOSInstallModal,
    hideIOSInstallModal: hideIOSInstallModal,
    isPWAInstalled: isPWAInstalled
  };
})();
