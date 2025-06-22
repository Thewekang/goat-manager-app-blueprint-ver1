// Service Worker for Goat Manager App
const CACHE_NAME = 'goat-manager-v1';
const urlsToCache = [
  '/',
  '/static/css/style.css',
  '/static/js/script.js',
  '/static/icons/icon-192.png',
  '/static/manifest.json'
];

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function(cache) {
        return cache.addAll(urlsToCache);
      })
  );
});

self.addEventListener('fetch', function(event) {
  event.respondWith(
    caches.match(event.request)
      .then(function(response) {
        // Return cached version or fetch from network
        return response || fetch(event.request);
      }
    )
  );
});
