"""ตัววัดความเร็วของระบบแบบเบา ๆ ในหน่วยความจำ — ป้อนหน้า "ตรวจสอบระบบ" (1 ต.ค. 69)

ที่มา: เครื่อง Prod ที่เปิดทดสอบ 24/7 หน่วงทั้งตอนยื่นคำขอและดูของ แต่หน้าตรวจสอบระบบบอกได้แค่ "ต่อฐานข้อมูลติด"
ตอบไม่ได้ว่าช้าที่ไหน — ต้องมีตัวเลขจริงของ (1) แต่ละ request ใช้เวลาเท่าไหร่ (2) event loop ถูกบล็อกไหม

ponytail: เก็บใน deque ของ process เดียว (prod รัน --workers 1) รีสตาร์ตแล้วหาย — พอสำหรับ "ตอนนี้ช้าเพราะอะไร"
จะดูย้อนหลังเป็นวัน/หลาย worker ค่อยย้ายไป Prometheus
"""
import asyncio
import time
from collections import deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send

WINDOW_SECONDS = 300          # ช่วงที่สรุปให้ดู (5 นาทีล่าสุด)
_MAX_SAMPLES = 5000           # ~16 req/วินาที ตลอด 5 นาที — เกินนี้ทิ้งของเก่า
_requests: deque[tuple[float, str, float, int]] = deque(maxlen=_MAX_SAMPLES)  # (เวลา, เส้นทาง, ms, status)
_loop_lag_ms: deque[tuple[float, float]] = deque(maxlen=WINDOW_SECONDS)       # (เวลา, ms) วินาทีละ 1 ค่า
_LAG_INTERVAL = 1.0


class PerfMiddleware:
    """จับเวลาทุก HTTP request + แนบ header `X-Process-Time` (ms ที่ใช้ในเซิร์ฟเวอร์)

    หน้าเว็บเอา header นี้ไปลบออกจากเวลาไป-กลับที่เบราว์เซอร์วัดได้ = เวลาที่หายไปกับเครือข่าย/nginx
    เป็น ASGI middleware ล้วน (ไม่ใช้ BaseHTTPMiddleware ที่ครอบ response เป็น stream แล้วช้าลงเอง)
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                ms = (time.perf_counter() - started) * 1000
                message.setdefault("headers", []).append((b"x-process-time", f"{ms:.1f}".encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # ใช้ path แม่แบบของ route (/borrow-requests/{request_id}) ไม่ใช่ URL จริง — ไม่งั้นสถิติแตกเป็นร้อยบรรทัด
            route = scope.get("route")
            path = getattr(route, "path", None) or ("/uploads/*" if scope["path"].startswith("/uploads") else "อื่น ๆ")
            _requests.append((time.time(), f"{scope['method']} {path}", (time.perf_counter() - started) * 1000, status))


async def loop_lag_monitor() -> None:
    """วัดว่า event loop ตื่นช้ากว่ากำหนดเท่าไหร่ทุกวินาที — งานที่ไม่ยอมคืน loop (bcrypt, สร้าง PDF, อ่านไฟล์ใหญ่)
    ทำให้ request ของ **ทุกคน** ค้างพร้อมกันเพราะมี worker เดียว ตัวเลขนี้คือหลักฐานตรงที่สุดของอาการนั้น"""
    loop = asyncio.get_running_loop()
    while True:
        t = loop.time()
        await asyncio.sleep(_LAG_INTERVAL)
        _loop_lag_ms.append((time.time(), max(0.0, (loop.time() - t - _LAG_INTERVAL) * 1000)))


def _pct(sorted_values: list[float], p: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * p))] if sorted_values else 0.0


def summary(now: float | None = None) -> dict:
    """สรุป 5 นาทีล่าสุด: ภาพรวม + เส้นทางที่ช้าที่สุด + event loop lag (ฟังก์ชันบริสุทธิ์ต่อข้อมูลใน deque)"""
    now = now or time.time()
    recent = [r for r in _requests if r[0] >= now - WINDOW_SECONDS]
    durations = sorted(r[2] for r in recent)
    by_path: dict[str, list[float]] = {}
    for _, path, ms, _ in recent:
        by_path.setdefault(path, []).append(ms)
    slowest = sorted(
        ({"path": p, "count": len(v), "avg_ms": round(sum(v) / len(v), 1),
          "p95_ms": round(_pct(sorted(v), 0.95), 1), "max_ms": round(max(v), 1)} for p, v in by_path.items()),
        key=lambda x: x["p95_ms"], reverse=True)[:8]
    lags = [ms for ts, ms in _loop_lag_ms if ts >= now - WINDOW_SECONDS]
    return {
        "window_minutes": WINDOW_SECONDS // 60,
        "count": len(recent),
        "per_minute": round(len(recent) / (WINDOW_SECONDS / 60), 1),
        "avg_ms": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "p95_ms": round(_pct(durations, 0.95), 1),
        "max_ms": round(durations[-1], 1) if durations else 0.0,
        "errors_5xx": sum(1 for r in recent if r[3] >= 500),
        "slow_over_1s": sum(1 for r in recent if r[2] >= 1000),
        "slowest": slowest,
        "loop_lag_max_ms": round(max(lags), 1) if lags else 0.0,
        "loop_lag_avg_ms": round(sum(lags) / len(lags), 1) if lags else 0.0,
    }
