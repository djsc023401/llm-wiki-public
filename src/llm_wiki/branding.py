from __future__ import annotations

import binascii
import json
import math
import struct
import zlib


THEME_COLOR = "#2f6f73"
BACKGROUND_COLOR = "#eef1ec"


def app_head_links() -> str:
    return f"""
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/icons/app-icon-192.png">
  <meta name="theme-color" content="{THEME_COLOR}">
"""


def app_manifest() -> str:
    return json.dumps(
        {
            "name": "llm-wiki 노트",
            "short_name": "llm-wiki",
            "description": "개인 지식 작업공간",
            "start_url": "/notes",
            "scope": "/",
            "display": "standalone",
            "background_color": BACKGROUND_COLOR,
            "theme_color": THEME_COLOR,
            "icons": [
                {
                    "src": "/icons/app-icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": "/icons/app-icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": "/favicon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any",
                },
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def service_worker_js() -> str:
    return """
self.addEventListener("push", (event) => {
  let payload = {};
  if (event.data) {
    try {
      payload = event.data.json();
    } catch (_error) {
      payload = { body: event.data.text() };
    }
  }
  const title = payload.title || "llm-wiki 알림";
  const options = {
    body: payload.body || "확인할 항목이 있습니다.",
    icon: "/icons/app-icon-192.png",
    badge: "/icons/app-icon-192.png",
    tag: payload.tag || "llm-wiki",
    data: { url: payload.url || "/notes" }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = new URL((event.notification.data && event.notification.data.url) || "/notes", self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if ("focus" in client) {
        await client.focus();
        if ("navigate" in client) return client.navigate(targetUrl);
        return;
      }
    }
    if (clients.openWindow) return clients.openWindow(targetUrl);
  })());
});
""".strip()


def app_icon_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="llm-wiki">
  <defs>
    <linearGradient id="bg" x1="80" y1="64" x2="448" y2="448" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#2f6f73"/>
      <stop offset="1" stop-color="#8a6f39"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="18" stdDeviation="18" flood-color="#1d2421" flood-opacity=".24"/>
    </filter>
  </defs>
  <rect width="512" height="512" rx="104" fill="url(#bg)"/>
  <g filter="url(#shadow)">
    <path d="M178 168h188c20 0 36 16 36 36v192c0 20-16 36-36 36H178c-20 0-36-16-36-36V204c0-20 16-36 36-36Z" fill="#fffefa"/>
    <path d="M118 224h188c20 0 36 16 36 36v132c0 20-16 36-36 36H118c-20 0-36-16-36-36V260c0-20 16-36 36-36Z" fill="#dff0ee" opacity=".96"/>
    <path d="M166 138h188c20 0 36 16 36 36v132c0 20-16 36-36 36H166c-20 0-36-16-36-36V174c0-20 16-36 36-36Z" fill="#fffefa" opacity=".92"/>
    <path d="M178 204h178" stroke="#2f6f73" stroke-width="20" stroke-linecap="round"/>
    <path d="M178 256h132" stroke="#8a6f39" stroke-width="18" stroke-linecap="round"/>
    <path d="M178 306h150" stroke="#bfc9bc" stroke-width="18" stroke-linecap="round"/>
  </g>
</svg>"""


def app_icon_png(size: int) -> bytes:
    if size not in {192, 512}:
        raise ValueError("unsupported icon size")
    pixels = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            t = (x + y) / max(1, (size - 1) * 2)
            color = _mix((47, 111, 115), (138, 111, 57), t)
            _set_pixel(pixels, size, x, y, (*color, 255))

    corner = int(size * 0.205)
    for y in range(size):
        for x in range(size):
            if not _inside_rounded_rect(x, y, 0, 0, size, size, corner):
                _set_pixel(pixels, size, x, y, (0, 0, 0, 0))

    _rounded_rect(pixels, size, 0.29, 0.33, 0.49, 0.51, 0.07, (30, 40, 37, 54))
    _rounded_rect(pixels, size, 0.35, 0.27, 0.44, 0.53, 0.07, (255, 254, 250, 255))
    _rounded_rect(pixels, size, 0.18, 0.43, 0.48, 0.41, 0.07, (223, 240, 238, 245))
    _rounded_rect(pixels, size, 0.28, 0.21, 0.49, 0.42, 0.07, (255, 254, 250, 236))
    _rounded_rect(pixels, size, 0.35, 0.38, 0.38, 0.04, 0.02, (47, 111, 115, 255))
    _rounded_rect(pixels, size, 0.35, 0.50, 0.28, 0.035, 0.018, (138, 111, 57, 255))
    _rounded_rect(pixels, size, 0.35, 0.61, 0.33, 0.035, 0.018, (191, 201, 188, 255))
    return _encode_png(size, size, bytes(pixels))


def _mix(left: tuple[int, int, int], right: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    eased = max(0.0, min(1.0, t))
    return tuple(round(left[i] + (right[i] - left[i]) * eased) for i in range(3))


def _rounded_rect(
    pixels: bytearray,
    canvas: int,
    x_frac: float,
    y_frac: float,
    w_frac: float,
    h_frac: float,
    r_frac: float,
    color: tuple[int, int, int, int],
) -> None:
    x = int(canvas * x_frac)
    y = int(canvas * y_frac)
    w = int(canvas * w_frac)
    h = int(canvas * h_frac)
    r = int(canvas * r_frac)
    for py in range(max(0, y), min(canvas, y + h)):
        for px in range(max(0, x), min(canvas, x + w)):
            if _inside_rounded_rect(px, py, x, y, w, h, r):
                _blend_pixel(pixels, canvas, px, py, color)


def _inside_rounded_rect(px: int, py: int, x: int, y: int, w: int, h: int, r: int) -> bool:
    if r <= 0:
        return x <= px < x + w and y <= py < y + h
    cx = min(max(px, x + r), x + w - r - 1)
    cy = min(max(py, y + r), y + h - r - 1)
    return math.hypot(px - cx, py - cy) <= r


def _blend_pixel(pixels: bytearray, width: int, x: int, y: int, color: tuple[int, int, int, int]) -> None:
    idx = (y * width + x) * 4
    sr, sg, sb, sa = color
    if sa >= 255:
        pixels[idx : idx + 4] = bytes(color)
        return
    da = pixels[idx + 3]
    alpha = sa / 255
    out_a = sa + da * (1 - alpha)
    if out_a <= 0:
        pixels[idx : idx + 4] = b"\x00\x00\x00\x00"
        return
    for offset, source in enumerate((sr, sg, sb)):
        dest = pixels[idx + offset]
        pixels[idx + offset] = round((source * sa + dest * da * (1 - alpha)) / out_a)
    pixels[idx + 3] = round(out_a)


def _set_pixel(pixels: bytearray, width: int, x: int, y: int, color: tuple[int, int, int, int]) -> None:
    idx = (y * width + x) * 4
    pixels[idx : idx + 4] = bytes(color)


def _encode_png(width: int, height: int, rgba: bytes) -> bytes:
    stride = width * 4
    scanlines = b"".join(b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(height))
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            _png_chunk(b"IDAT", zlib.compress(scanlines, level=9)),
            _png_chunk(b"IEND", b""),
        ]
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = binascii.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)
