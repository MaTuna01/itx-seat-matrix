// Service worker — 푸시 수신 + 딥링크 + 오프라인 캐시 (PLAN 8·10절, D-20/D-21).
//
// 이 파일은 public/ 에 있어 Vite가 **해시 없이** 그대로 복사한다. 파일명이 고정이어야
// 브라우저가 같은 워커의 갱신으로 인식한다. 캐시를 갈아엎을 때는 CACHE 를 올려라.
//
// ★ /api 응답은 절대 캐시하지 않는다. 낡은 좌석 데이터를 최신인 것처럼 보여주는 것이
// 이 앱에서 가장 위험한 실패다 (D-17). 열차 안 회선 끊김 대응은 api.js 의
// localStorage 매트릭스 캐시가 담당하고, 그쪽은 "언제 받은 값인지"를 화면에 표시한다.

// v2: 판정 요약에 지연 착석 그룹이 추가됐다 (D-46). 올리지 않으면 홈화면 PWA가
// 앱을 완전히 종료할 때까지 옛 화면을 계속 보여준다.
const CACHE = "itx-shell-v6";
const SHELL = "/";

self.addEventListener("install", (event) => {
  // 셸 프리캐시가 실패해도 설치는 성공시킨다 (오프라인에서 갱신될 때 등).
  // 실패로 두면 워커 자체가 설치되지 않아 **푸시 수신까지 함께 죽는다** —
  // 오프라인 캐시는 보조 기능이고 알림이 본 기능이다.
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.add(SHELL))
      .catch(() => {})
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// 정적 자산은 캐시 우선 + 백그라운드 갱신. 화면 진입(navigate)은 네트워크 우선이고
// 실패하면 캐시된 셸을 준다 — 터널에서 앱을 열어도 흰 화면이 아니다.
self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // ★ 네트워크 전용

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match(SHELL).then((hit) => hit || Response.error()))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((hit) => {
      const fresh = fetch(request)
        .then((res) => {
          if (res.ok) caches.open(CACHE).then((cache) => cache.put(request, res.clone()));
          return res;
        })
        .catch(() => hit || Response.error());
      return hit || fresh;
    })
  );
});

// ── 푸시 수신 ─────────────────────────────────────────────────────────
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { title: "ITX 좌석", body: event.data ? event.data.text() : "" };
  }

  const subId = data.subscription_id;
  event.waitUntil(
    self.registration.showNotification(data.title || "ITX 좌석", {
      body: data.body || "",
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      // 구독당 한 칸만 쓴다. 새 알림이 옛 알림을 대체해야 한다 — "자리 팔렸음"과
      // "잔여 없음"이 잠금화면에 나란히 남으면 모순 메시지 2건이 된다 (D-20).
      tag: subId ? `itx-sub-${subId}` : "itx",
      renotify: true,
      data: { url: data.url || "/", kind: data.kind || null },
    })
  );
});

// ── 알림 탭 → 매트릭스 딥링크 (D-20) ─────────────────────────────────
// "알림은 앱을 열 시점을 알리는 장치"(D-2/D-9)의 마지막 연결 고리다.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";

  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of windows) {
        // iOS 홈화면 웹앱에서는 navigate()가 막힐 수 있다. 그때는 앱에 메시지로
        // 알려 라우팅을 맡긴다 — 포커스만 되고 화면이 안 바뀌면 알림의 절반이 무용해진다.
        try {
          await client.navigate(target);
        } catch {
          client.postMessage({ type: "itx:navigate", url: target });
        }
        return client.focus();
      }
      return self.clients.openWindow(target);
    })()
  );
});

// ── endpoint 회전 대응 (D-20) ────────────────────────────────────────
// iOS는 푸시 endpoint를 조용히 회전시킨다. 재구독해서 서버에 다시 등록하지 않으면
// 그날부터 알림이 오지 않고, 사용자는 그 사실을 알 방법이 없다.
// (옛 행은 서버가 첫 발송에서 410을 받아 스스로 지운다.)
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil(
    (async () => {
      const key =
        event.oldSubscription &&
        event.oldSubscription.options &&
        event.oldSubscription.options.applicationServerKey;
      if (!key) return;
      const fresh = await self.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: key,
      });
      const json = fresh.toJSON();
      await fetch("/api/push/devices", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys, label: null }),
      });
    })()
  );
});
