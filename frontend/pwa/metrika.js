// NURA — Яндекс.Метрика helper
// Счётчик: 109200181

(function() {
  (function(m,e,t,r,i,k,a){
    m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
    m[i].l=1*new Date();
    k=e.createElement(t),a=e.getElementsByTagName(t)[0];
    k.async=1;k.src=r;a.parentNode.insertBefore(k,a)
  })(window,document,'script','https://mc.yandex.ru/metrika/tag.js','ym');

  ym(109200181,'init',{
    clickmap:    true,
    trackLinks:  true,
    accurateTrackBounce: true,
    webvisor:    false,
    ecommerce:   'dataLayer',
  });

  window.nuraTrack = function(goalName, params) {
    try {
      if (typeof ym === 'function') {
        ym(109200181, 'reachGoal', goalName, params || {});
      }
    } catch(e) {}
  };

  var path = window.location.pathname;

  if (window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true) {
    window.nuraTrack('pwa_opened');
  }

  if (path.startsWith('/app')) {
    var section = path === '/app' || path === '/app/'
      ? 'home'
      : path.replace('/app/', '') || 'home';
    window.nuraTrack('app_screen_view', { screen: section });
  }

  if (path === '/success' || path.includes('success')) {
    window.nuraTrack('payment_success', { product: 'matrix_890' });
  }

  window.addEventListener('appinstalled', function() {
    window.nuraTrack('pwa_installed', { platform: 'android' });
    try { localStorage.setItem('pwa_installed', '1'); } catch(e) {}
  });
})();
