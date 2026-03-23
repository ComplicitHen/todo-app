const CACHE = "todo-v1";
const ASSETS = ["/", "/manifest.json"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  // API-anrop: alltid från nätverket
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(fetch(e.request).catch(() =>
      new Response(JSON.stringify({ error: "Offline" }), {
        headers: { "Content-Type": "application/json" }
      })
    ));
    return;
  }
  // Övrigt: cache-first
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
