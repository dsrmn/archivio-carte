// Service worker: permette di aprire l'app anche senza connessione.
// Prova prima la rete (così ricevi gli aggiornamenti) e ripiega sulla copia salvata.
const CACHE = "dsr-archive-v9";
// Immagini delle carte: salvate a parte, restano anche dopo gli aggiornamenti dell'app.
const IMG_CACHE = "dsr-img-v1", IMG_MAX = 4000;
const FILES = ["./", "index.html", "manifest.webmanifest", "icon.svg"];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => (k.startsWith("dsr-archive-") && k !== CACHE) || (k.startsWith("dsr-img-") && k !== IMG_CACHE)).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
// Prima la copia salvata, poi la rete: le immagini di una carta non cambiano
// (quando cambi immagine cambia anche l'indirizzo).
async function cachedImage(req){
  const cache = await caches.open(IMG_CACHE);
  const hit = await cache.match(req.url);
  if (hit) return hit;
  let res;
  try { res = await fetch(req.url, {mode: "cors", credentials: "omit", referrerPolicy: "no-referrer"}); }
  catch { return fetch(req); }  // sito senza CORS: la mostra comunque, senza salvarla
  if (res.ok){
    await cache.put(req.url, res.clone());
    trimImages(cache);
  }
  return res;
}
let trimming = false;
async function trimImages(cache){
  if (trimming) return; trimming = true;
  try { const keys = await cache.keys(); for (const k of keys.slice(0, Math.max(0, keys.length - IMG_MAX))) await cache.delete(k); }
  finally { trimming = false; }
}
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (req.destination === "image" && url.origin !== self.location.origin && /^https:$/.test(url.protocol)){
    e.respondWith(cachedImage(req)); return;
  }
  if (url.origin !== self.location.origin) return;
  e.respondWith(
    fetch(req).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req).then(r => r || caches.match("index.html")))
  );
});
