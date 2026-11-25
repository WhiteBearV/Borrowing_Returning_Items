"""การ์ด "สำรองข้อมูลขึ้น Google Drive" ในหน้าตรวจสอบระบบ (25 พ.ย. 69) — ฟังก์ชันบริสุทธิ์ ไม่แตะ DB"""
from datetime import datetime, timedelta, timezone

from app.services.system_check_service import OFFSITE_STALE_HOURS, _offsite_backup_check

NOW = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def test_offsite_backup_card_states():
    ok = _offsite_backup_check(f"OK {_iso(7)} 16 files", NOW)
    assert ok["status"] == "ok" and "16 ไฟล์" in ok["value"]
    assert _offsite_backup_check(f"OK {_iso(OFFSITE_STALE_HOURS + 1)} 16 files", NOW)["status"] == "error"
    assert _offsite_backup_check(f"FAILED {_iso(1)}", NOW)["status"] == "error"
    assert _offsite_backup_check("OK not-a-date", NOW)["status"] == "error"
    assert _offsite_backup_check(None, NOW)["status"] == "warn"   # เครื่อง dev / ยังไม่ได้ตั้งค่า
    assert _offsite_backup_check("", NOW)["status"] == "warn"
