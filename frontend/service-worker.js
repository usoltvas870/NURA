importScripts('/pwa-release.js');

const CACHE_NAME = `nura-${self.NURA_RELEASE_ID}`;
const STATIC_ASSETS = [
  '/', '/offline.html', '/mini.html', '/success.html', '/app/', '/app/index.html',
  '/app/home-v9.css', '/app/nura-shell-v1.css', '/app/chat.html', '/app/chat-v1-2.css',
  '/app/tarot.html', '/app/tarot-v2-1.css', '/app/success.html', '/app/profile.html',
  '/app/profile-v1.css', '/app/nura-pwa.js', '/app/nura-pwa.css', '/manifest.json',
  '/pwa-install.js', '/theme.css', '/icons/icon-192.png', '/icons/icon-512.png',
  '/icons/apple-touch-icon.png'
];
const STATIC_PATHS = new Set(STATIC_ASSETS);

function isPrivatePath(url) {
  return url.pathname.startsWith('/api/') || url.pathname.startsWith('/report/') ||
    url.pathname.startsWith('/webhook/') || /(?:session|identity|subscription|quota|chat|telegram|notification)/i.test(url.pathname);
}

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)));
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((key) => key.startsWith('nura-') && key !== CACHE_NAME).map((key) => caches.delete(key))
  )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin || isPrivatePath(url)) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/offline.html')));
    return;
  }
  if (!STATIC_PATHS.has(url.pathname)) return;
  event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
});

self.addEventListener('push', (event) => {
  if (!event.data) return;
  let data;
  try { data = event.data.json(); } catch (_) { return; }
  event.waitUntil(self.registration.showNotification(data.title || 'NURA', {
    body: data.body || 'Открой NURA', icon: '/icons/icon-192.png', badge: '/icons/icon-192.png',
    data: { url: data.url || '/app/' }, tag: data.tag || 'nura-default', renotify: false
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/app/';
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
    for (const client of list) {
      if (client.url.includes(self.location.origin) && 'focus' in client) {
        client.navigate(target);
        return client.focus();
      }
    }
    return clients.openWindow(target);
  }));
});
