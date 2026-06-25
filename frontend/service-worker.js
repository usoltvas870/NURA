const CACHE_NAME = 'nura-v14';
const STATIC_ASSETS = [
  '/',
  '/offline.html',
  '/mini.html',
  '/success.html',
  '/app/',
  '/app/index.html',
  '/app/chat.html',
  '/app/tarot.html',
  '/app/profile.html',
  '/app/nura-pwa.js',
  '/app/nura-pwa.css',
  '/manifest.json',
  '/pwa-install.js',
  '/theme.css',
  '/nura-ds.css',
  '/static/nura-ds.css',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/apple-touch-icon.png'
];

self.addEventListener('install', function(e) {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(STATIC_ASSETS).catch(function(err) {
        console.warn('SW install: cache.addAll failed for some assets', err);
      });
    })
  );
});

self.addEventListener('message', function(event) {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) { return k !== CACHE_NAME; }).map(function(k) {
          return caches.delete(k);
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  var url = new URL(e.request.url);

  if (url.pathname.startsWith('/api/')) return;
  if (url.pathname.startsWith('/report/')) return;
  if (url.pathname.startsWith('/webhook/')) return;

  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(function() {
        return caches.match('/offline.html');
      })
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then(function(cached) {
      return cached || fetch(e.request).then(function(response) {
        if (response && response.status === 200 && response.type === 'basic') {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(e.request, clone);
          });
        }
        return response;
      }).catch(function() {
        if (e.request.destination === 'image') {
          return caches.match('/icons/icon-192.png');
        }
        return caches.match('/offline.html');
      });
    })
  );
});

self.addEventListener('push', function(e) {
  if (!e.data) return;
  var d;
  try { d = e.data.json(); } catch (_) { return; }
  e.waitUntil(
    self.registration.showNotification(d.title || 'NURA', {
      body: d.body || 'Открой NURA',
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      vibrate: [100, 50, 100],
      data: { url: d.url || '/app/' },
      tag: d.tag || 'nura-default',
      renotify: false
    })
  );
});

self.addEventListener('notificationclick', function(e) {
  e.notification.close();
  var target = (e.notification.data && e.notification.data.url) || '/app/';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(list) {
      for (var i = 0; i < list.length; i++) {
        var c = list[i];
        if (c.url.includes(self.location.origin) && 'focus' in c) {
          c.navigate(target);
          return c.focus();
        }
      }
      return clients.openWindow(target);
    })
  );
});
