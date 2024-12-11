/* creates a cache caches the offline html page */
self.addEventListener("install", event => {
    event.waitUntil(
        caches.open("static").then(cache => {
            return cache.addAll(["./", "./static/offline.html", "./static/manifest.json", "./static/icons/zunoot-512x512.png", "/static/icons/zunoot-192x192.png"]);
        })
    );
    self.skipWaiting()
});

/*renders the offline page if any navigation fails */
self.addEventListener("fetch", event => {
    if (event.request.mode === "navigate") {
        event.respondWith(
            fetch(event.request).catch(() => {
                return caches.match("./static/offline.html");
            })
        );
    } else if (event.request.destination === "image" || event.request.url.includes("/static/icons")) {
        event.respondWith(
            caches.match(event.request).then(cacheResponse => cacheResponse || fetch(event.request))
        );
    }
});