"""ตัววัดความเร็วในหน้าตรวจสอบระบบ (1 ต.ค. 69) — ที่มา: Prod หน่วงแต่หน้าตรวจสอบบอกไม่ได้ว่าช้าที่ไหน"""
import time

from httpx import AsyncClient

from app.utils import perf
from tests.conftest import auth

PERF_KEYS = {"api_speed", "api_errors", "event_loop", "db_pool", "db_connections", "db_activity"}


def test_perf_summary_math():
    """สรุปจากข้อมูลใน deque: นับเฉพาะในหน้าต่างเวลา · เรียงเส้นทางตาม p95 · นับ 5xx และที่เกิน 1 วินาที"""
    saved = list(perf._requests)
    perf._requests.clear()
    try:
        now = time.time()
        perf._requests.extend([(now - 1000, "GET /old", 9999.0, 200)]             # นอกหน้าต่าง 5 นาที
                              + [(now, "GET /fast", 10.0, 200)] * 9
                              + [(now, "GET /slow", 1500.0, 500)])
        s = perf.summary(now)
        assert s["count"] == 10 and s["errors_5xx"] == 1 and s["slow_over_1s"] == 1
        assert s["avg_ms"] == 159.0 and s["max_ms"] == 1500.0
        assert [e["path"] for e in s["slowest"]] == ["GET /slow", "GET /fast"]
    finally:
        perf._requests.clear()
        perf._requests.extend(saved)


async def test_system_check_reports_performance(client: AsyncClient, superadmin_token: str, student_token: str):
    r = await client.get("/health")
    assert float(r.headers["x-process-time"]) >= 0       # หน้าเว็บใช้ค่านี้แยกเวลาที่เสียระหว่างทาง
    await client.get("/equipment", headers=auth(student_token))

    assert (await client.get("/change-requests/system-check", headers=auth(student_token))).status_code == 403
    data = (await client.get("/change-requests/system-check", headers=auth(superadmin_token))).json()
    health = {h["key"]: h for h in data["health"]}
    assert PERF_KEYS <= health.keys()
    assert all(h["status"] in ("ok", "warn", "error") for h in health.values())
    # path เป็นแม่แบบของ route ไม่ใช่ URL จริง (ไม่มี id/ข้อมูลผู้ใช้หลุดเข้าสถิติ) — เช็คที่ข้อมูลดิบ เพราะตาราง
    # 8 อันดับช้าสุดขึ้นกับว่าเทสอื่นยิงอะไรไปก่อนหน้า
    paths = {r[1] for r in perf._requests}
    assert "GET /equipment" in paths and "GET /change-requests/system-check" in paths
    assert not any("?" in p_ for p_ in paths)
    assert 0 < len(data["slowest_endpoints"]) <= 8
    assert {"path", "count", "avg_ms", "p95_ms", "max_ms"} <= data["slowest_endpoints"][0].keys()
