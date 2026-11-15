// NFR-03: service worker for teachers. Network first; when there is no
// connection the last saved copy of the page is shown instead.
const CACHE = "itmatic-teacher-v1";
const OFFLINE_PAGES = [/^\/teacher\//, /^\/lesson\/\d+\/$/, /^\/static\//];

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || !OFFLINE_PAGES.some((re) => re.test(url.pathname))) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((c) => c.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request, { ignoreSearch: false }))
  );
});
