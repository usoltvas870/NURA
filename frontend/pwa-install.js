// NURA PWA Install UI
// Android: intercept beforeinstallprompt, show banner on trigger
// iOS: detect Safari + not standalone -> show instruction modal

function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
}

function isAndroid() {
  return /Android/.test(navigator.userAgent);
}

function isPWAInstalled() {
  return window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true;
}

function getIOSVersion() {
  var m = navigator.userAgent.match(/OS (\d+)_/);
  return m ? parseInt(m[1]) : 0;
}

var _deferredPrompt = null;

window.addEventListener('beforeinstallprompt', function(e) {
  e.preventDefault();
  _deferredPrompt = e;
});

window.addEventListener('appinstalled', function() {
  _deferredPrompt = null;
  hideInstallBanner();
  if (typeof ym !== 'undefined') ym(window._YM_ID, 'reachGoal', 'pwa_installed');
});

function triggerAndroidInstall() {
  if (!_deferredPrompt) return false;
  _deferredPrompt.prompt();
  _deferredPrompt.userChoice.then(function(choice) {
    _deferredPrompt = null;
    if (choice.outcome === 'accepted') {
      hideInstallBanner();
    }
  });
  return true;
}

function showInstallBanner() {
  if (isPWAInstalled()) return;
  if (sessionStorage.getItem('install_banner_dismissed')) return;
  if (!_deferredPrompt) return;
  var banner = document.getElementById('pwa-install-banner');
  if (banner) banner.style.display = 'flex';
}

function hideInstallBanner() {
  var banner = document.getElementById('pwa-install-banner');
  if (banner) banner.style.display = 'none';
}

function dismissInstallBanner() {
  sessionStorage.setItem('install_banner_dismissed', '1');
  hideInstallBanner();
}

function showIOSInstallModal() {
  var modal = document.getElementById('pwa-ios-modal');
  if (modal) modal.style.display = 'flex';
}

function hideIOSInstallModal() {
  var modal = document.getElementById('pwa-ios-modal');
  if (modal) modal.style.display = 'none';
  sessionStorage.setItem('ios_install_shown', '1');
}

function initPWAInstall() {
  if (isPWAInstalled()) return;
  if (isAndroid()) {
    setTimeout(function() { showInstallBanner(); }, 3000);
  }
  if (isIOS() && getIOSVersion() >= 15) {
    if (!sessionStorage.getItem('ios_install_shown')) {
      setTimeout(function() { showIOSInstallModal(); }, 4000);
    }
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initPWAInstall);
} else {
  initPWAInstall();
}

window.NURA_PWA = {
  showInstallBanner: showInstallBanner,
  hideInstallBanner: hideInstallBanner,
  dismissInstallBanner: dismissInstallBanner,
  triggerAndroidInstall: triggerAndroidInstall,
  showIOSInstallModal: showIOSInstallModal,
  hideIOSInstallModal: hideIOSInstallModal,
  isPWAInstalled: isPWAInstalled
};
