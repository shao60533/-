// Service Worker - minimal offline support
const CACHE_NAME = 'stockai-v1';
const PRECACHE = ['/', '/static/css/style.css', '/static/js/app.js'];

self.addEventListener('install', e => {
    e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(PRECACHE)));
    self.skipWaiting();
});

self.addEventListener('activate', e => {
    e.waitUntil(caches.keys().then(keys =>
        Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ));
    self.clients.claim();
});

self.addEventListener('fetch', e => {
    // Network-first for API calls, cache-first for static assets
    if (e.request.url.includes('/api/')) {
        e.respondWith(fetch(e.request).catch(() => new Response('{"error":"offline"}', { headers: { 'Content-Type': 'application/json' } })));
    } else {
        e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
    }
});
