// ERSKI PWA Service Worker
// 策略:app shell(首頁/圖示)快取備援;所有 /api/ 請求一律直接打網路,絕不快取,
// 避免價格、預約狀態、額度這類會即時變動的資料被快取成舊資料。

const CACHE_NAME = "erski-shell-v1";
const APP_SHELL = ["/", "/manifest.json", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // API 請求:一律直接打網路,不做任何快取(避免價格/預約資料過期)
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(fetch(event.request));
    return;
  }

  // 其他請求(頁面本身/圖示等):網路優先,離線時才退回快取
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
