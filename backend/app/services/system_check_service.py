"""หน้าตรวจสุขภาพข้อมูลสำหรับผู้ดูแลระบบสูงสุด — อ่านอย่างเดียว (feedback อาจารย์ 5 ก.ย. 69)

อาจารย์ขอ "เช็คฐานข้อมูลแบบลึกและละเอียด" — ทำเป็น **query ตายตัวที่เขียนไว้ล่วงหน้า** ไม่ใช่ช่องพิมพ์ SQL
เพราะช่องรัน SQL ในเว็บ = ช่องโหว่ถาวรที่ลบ audit log ของตัวเองได้ ซึ่งขัดกับข้อ 1 ที่อาจารย์ต้องการเอง
ถ้าวันหนึ่งต้อง query แปลก ๆ จริง ใช้ psql ผ่าน SSH ซึ่งมีอยู่แล้ว

ทุก query ในไฟล์นี้ต้องเป็น SELECT เท่านั้น — ห้ามมี INSERT/UPDATE/DELETE เด็ดขาด
"""
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import engine
from app.models.audit_log import AuditLog
from app.models.borrow_item import BorrowItem
from app.models.borrow_request import BorrowRequest
from app.models.equipment import Equipment
from app.models.user import User
from app.services.borrow_service import STOCK_RETURN_CONDITIONS
from app.utils import perf

# ตารางที่นับจำนวนแถวให้ดู — ชื่อไทยคู่กันเพื่อให้คนที่ไม่ได้เขียนโค้ดอ่านออก
_COUNTED_TABLES = [
    ("users", "บัญชีผู้ใช้"),
    ("equipment", "อุปกรณ์ในคลัง"),
    ("borrow_requests", "คำขอยืม"),
    ("borrow_items", "รายการในคำขอ"),
    ("audit_logs", "ประวัติการใช้งาน"),
    ("notifications", "การแจ้งเตือน"),
    ("equipment_parts", "ชิ้นส่วนที่ติดตั้ง"),
    ("change_requests", "คำขอแก้ไขข้อมูล"),
]

STALE_UNVERIFIED_DAYS = 30
# ถือว่า "กำลังใช้งานอยู่" ถ้าเรียก API ภายในกี่นาที (users.last_seen_at) — ระบบไม่มี session ฝั่งเซิร์ฟเวอร์
# เพราะใช้ JWT ล้วน ตัวเลขนี้จึงเป็นค่าประมาณที่ดีที่สุดที่ทำได้โดยไม่ต้องเก็บ session แยก
ONLINE_WINDOW_MINUTES = 15
# ดิสก์เหลือน้อยกว่านี้ = เตือน (ไฟล์แนบ/รูปความเสียหายโตเงียบ ๆ จนดิสก์เต็มเป็นเคสที่เกิดจริง)
DISK_WARN_FREE_GB = 2.0
# เวลาที่เซิร์ฟเวอร์เริ่มทำงาน — ใช้บอก uptime (ไม่ต้องพึ่ง systemd/docker)
_STARTED_AT = datetime.now(timezone.utc)


def _dir_size_mb(path: str) -> float:
    """ขนาดโฟลเดอร์ (MB) — ไฟล์แนบโตเงียบ ๆ จนดิสก์เต็มเป็นเคสที่เกิดจริงในระบบแบบนี้"""
    root = Path(path)
    if not root.exists():
        return 0.0
    total = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    return round(total / 1024 / 1024, 2)


async def run_checks(db: AsyncSession) -> dict:
    """รวมผลตรวจทั้งหมดในครั้งเดียว — คืน dict ที่ frontend เอาไปแสดงตรง ๆ

    ผลลัพธ์แบ่งเป็น 2 ส่วน: `counts` (นับแถว) และ `issues` (สิ่งที่ผิดปกติและควรตามแก้)
    """
    counts = []
    for table, label in _COUNTED_TABLES:
        # ชื่อตารางมาจากค่าคงที่ในไฟล์นี้เท่านั้น ไม่ได้รับจากผู้ใช้ — ไม่มีทาง inject
        n = (await db.execute(text(f"SELECT count(*) FROM {table}"))).scalar() or 0
        counts.append({"table": table, "label": label, "count": n})

    issues = []

    async def add_issue(key: str, label: str, count: int, hint: str,
                        sample: list[str] | None = None) -> None:
        if count:
            issues.append({"key": key, "label": label, "count": count, "hint": hint,
                           "sample": sample or []})

    # สต็อกเกินจำนวนทั้งหมด — มี CheckConstraint กันอยู่แล้ว ตรวจซ้ำเผื่อข้อมูลเก่าก่อน migration 0016
    await add_issue(
        "stock_over_total", "อุปกรณ์ที่คงเหลือมากกว่าจำนวนทั้งหมด",
        (await db.execute(select(func.count()).select_from(Equipment)
                          .where(Equipment.quantity_available > Equipment.quantity_total))).scalar() or 0,
        "ตัวเลขสต็อกผิด ต้องปรับยอดคงเหลือให้ตรงของจริง",
    )
    # ยืมค้างอยู่แต่แถวอุปกรณ์ถูกลบถาวรไปแล้ว (equipment_id เป็น NULL จาก ON DELETE SET NULL)
    await add_issue(
        "orphan_borrow_items", "รายการยืมค้างที่อุปกรณ์ถูกลบไปแล้ว",
        (await db.execute(select(func.count()).select_from(BorrowItem)
                          .where(BorrowItem.equipment_id.is_(None), BorrowItem.returned == False))).scalar() or 0,  # noqa: E712
        "ของถูกลบทั้งที่ยังยืมไม่คืน — ตรวจว่าของอยู่ไหนแล้วปิดรายการให้ถูกต้อง",
    )
    # คำขอที่อนุมัติแล้วแต่ไม่มีรายการเลย — ปิดไม่ได้เพราะไม่มีอะไรให้คืน
    approved_no_items = (await db.execute(
        select(func.count()).select_from(BorrowRequest).where(
            BorrowRequest.status == "approved",
            ~select(BorrowItem.id).where(BorrowItem.borrow_request_id == BorrowRequest.id).exists(),
        )
    )).scalar() or 0
    await add_issue("approved_no_items", "คำขอที่อนุมัติแล้วแต่ไม่มีรายการ", approved_no_items,
                    "คำขอค้างสถานะถาวร ควรลบทิ้งหรือตรวจว่าเกิดจากอะไร")
    # สมัครแล้วไม่ยืนยันอีเมลสักที
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_UNVERIFIED_DAYS)
    await add_issue(
        "stale_unverified", f"บัญชีที่ยังไม่ยืนยันอีเมลเกิน {STALE_UNVERIFIED_DAYS} วัน",
        (await db.execute(select(func.count()).select_from(User)
                          .where(User.email_verified == False, User.created_at < cutoff))).scalar() or 0,  # noqa: E712
        "อาจเป็นการสมัครทิ้งไว้ ควรตรวจแล้วลบออก",
    )
    await add_issue(
        "no_price", "อุปกรณ์ที่ยังไม่มีราคา",
        (await db.execute(select(func.count()).select_from(Equipment)
                          .where(Equipment.unit_value.is_(None), Equipment.status != "retired"))).scalar() or 0,
        "คิดมูลค่าตามบัญชี/ค่าเสียหายไม่ได้จนกว่าจะกรอกราคา",
    )
    await add_issue(
        "no_acquired_at", "อุปกรณ์ที่ยังไม่มีวันที่ได้มา",
        (await db.execute(select(func.count()).select_from(Equipment)
                          .where(Equipment.acquired_at.is_(None), Equipment.status != "retired"))).scalar() or 0,
        "คำนวณอายุและค่าเสื่อมไม่ได้จนกว่าจะกรอกวันที่ได้มา",
    )

    mismatch_count, mismatch_sample = await _stock_reconcile(db)
    await add_issue(
        "stock_mismatch", "อุปกรณ์ที่ยอดคงเหลือไม่ตรงกับประวัติการยืม", mismatch_count,
        "ยอดคงเหลือ + ที่ยืมค้าง + ที่คืนแบบไม่เข้าคลัง ควรเท่ากับจำนวนทั้งหมด "
        "ถ้าไม่ตรงแปลว่ามีของหายไปจากยอดโดยไม่มีประวัติรองรับ (หรือเคยปรับยอดด้วยมือ — ดูได้ในหน้าประวัติการใช้งาน)",
        mismatch_sample,
    )

    oldest_log = (await db.execute(select(func.min(AuditLog.created_at)))).scalar()
    return {
        "counts": counts,
        "issues": issues,
        "health": await _health_checks(db),
        # เส้นทางที่ช้าที่สุดใน 5 นาทีล่าสุด — บอกได้ทันทีว่าหน้าไหนเป็นตัวถ่วง (path เป็นแม่แบบ ไม่มีข้อมูลผู้ใช้)
        "slowest_endpoints": perf.summary()["slowest"],
        "audit_log_since": oldest_log,
        "uploads_size_mb": _dir_size_mb(settings.UPLOAD_DIR),
        "checked_at": datetime.now(timezone.utc),
    }


SAMPLE_LIMIT = 5


async def _stock_reconcile(db: AsyncSession) -> tuple[int, list[str]]:
    """กระทบยอดสต็อก: จำนวนทั้งหมด ควรเท่ากับ คงเหลือ + ยืมค้าง + ที่คืนแบบไม่เข้าคลัง

    ระบบตัดสต็อกตอนอนุมัติและคืนเข้าเฉพาะสภาพ ok/returned_full เท่านั้น (ดู borrow_service) ดังนั้นสมการนี้
    ต้องเป็นจริงเสมอสำหรับของที่ยัง `available` — ถ้าไม่ตรงแปลว่ามีของหายจากยอดโดยไม่มีประวัติ เช่น
    บั๊กนำเข้าไฟล์ทะเบียนที่เคยเขียนทับ quantity_available จนของยืมไม่ได้ทั้งที่ยังอยู่บนชั้น

    ตรวจเฉพาะแถวที่ `status = 'available'` — ของที่ส่งซ่อม/สูญหาย/ปลดระวางถูกกันยอดคงเหลือเป็น 0 โดยตั้งใจ
    (borrow_service.return_item ตั้ง status ให้เมื่อรับคืนแบบชำรุด/สูญหาย) ถ้านับรวมจะเตือนผิดทุกแถว

    คืน (จำนวนแถวที่ไม่ตรง, ตัวอย่างรหัสไม่เกิน SAMPLE_LIMIT ตัว) — ต้องบอกด้วยว่าแถวไหน ไม่งั้นรู้ว่าเพี้ยน
    แต่ตามแก้ไม่ถูก
    """
    borrowed = (
        select(BorrowItem.equipment_id.label("eq"), func.sum(BorrowItem.quantity).label("qty"))
        .join(BorrowRequest, BorrowItem.borrow_request_id == BorrowRequest.id)
        .where(BorrowItem.returned == False, BorrowItem.item_status != "rejected",  # noqa: E712
               BorrowRequest.status == "approved")
        .group_by(BorrowItem.equipment_id).subquery()
    )
    # คืนแล้วแต่ของไม่กลับเข้าคลัง (ชำรุด/สูญหาย/ใช้หมด/ทิ้ง) — ยอดหายถาวรแต่ quantity_total ไม่ลด
    not_returned_to_stock = (
        select(BorrowItem.equipment_id.label("eq"), func.sum(BorrowItem.quantity).label("qty"))
        .where(BorrowItem.returned == True, BorrowItem.item_status != "rejected",  # noqa: E712
               func.coalesce(BorrowItem.condition_on_return, "").not_in(STOCK_RETURN_CONDITIONS))
        .group_by(BorrowItem.equipment_id).subquery()
    )
    accounted = (
        Equipment.quantity_available
        + func.coalesce(borrowed.c.qty, 0)
        + func.coalesce(not_returned_to_stock.c.qty, 0)
    )
    rows = (await db.execute(
        select(Equipment.code)
        .outerjoin(borrowed, borrowed.c.eq == Equipment.id)
        .outerjoin(not_returned_to_stock, not_returned_to_stock.c.eq == Equipment.id)
        .where(Equipment.status == "available", accounted != Equipment.quantity_total)
        .order_by(Equipment.code)
    )).scalars().all()
    return len(rows), list(rows[:SAMPLE_LIMIT])


def _fmt_uptime(seconds: float) -> str:
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d} วัน {h} ชม. {m} นาที" if d else (f"{h} ชม. {m} นาที" if h else f"{m} นาที")


async def _health_checks(db: AsyncSession) -> list[dict]:
    """สุขภาพของ "ระบบ" ไม่ใช่ของ "ข้อมูล" — ต่อฐานข้อมูลติดไหม งานตามเวลายังเดินอยู่ไหม ดิสก์เหลือเท่าไหร่

    ทุกอย่างวัดจากของจริงตอนกดดู ไม่ใช่ค่าที่จำไว้ล่วงหน้า — หน้าตรวจระบบที่โชว์ค่าที่ cache ไว้
    จะบอกว่า "ปกติ" ต่อไปอีกนานหลังระบบล่มไปแล้ว
    status: ok / warn / error — frontend ใช้เลือกสี
    """
    checks: list[dict] = []

    # 1) ฐานข้อมูล: ต่อติดไหม + ตอบช้าแค่ไหน (ping จริง ไม่ใช่เดาจากว่า query อื่นผ่าน)
    started = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        ms = round((time.perf_counter() - started) * 1000, 1)
        checks.append({
            "key": "database", "label": "การเชื่อมต่อฐานข้อมูล",
            "status": "ok" if ms < 200 else "warn",
            "value": f"ตอบใน {ms} ms",
            "hint": "" if ms < 200 else "ฐานข้อมูลตอบช้ากว่าปกติ ตรวจโหลดเครื่องหรือ query ที่ค้างอยู่",
        })
    except Exception as e:  # pragma: no cover - ถ้า DB ล่มจริง endpoint นี้ก็ไม่ถูกเรียกอยู่แล้ว
        checks.append({"key": "database", "label": "การเชื่อมต่อฐานข้อมูล", "status": "error",
                       "value": "ต่อไม่ได้", "hint": str(e)[:200]})

    # 2) เวอร์ชัน migration ที่ DB อยู่ — ไม่ตรงกับโค้ดคือสาเหตุอันดับต้น ๆ ของ 500 หลัง deploy
    try:
        version = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    except Exception:
        version = None
    checks.append({"key": "migration", "label": "เวอร์ชันโครงสร้างฐานข้อมูล (migration)",
                   "status": "ok" if version else "error",
                   "value": version or "อ่านไม่ได้",
                   "hint": "" if version else "ยังไม่ได้รัน alembic upgrade head บนเครื่องนี้"})

    # 3) ขนาดฐานข้อมูล
    try:
        size = (await db.execute(text(
            "SELECT pg_size_pretty(pg_database_size(current_database()))"))).scalar()
        checks.append({"key": "db_size", "label": "ขนาดฐานข้อมูล", "status": "ok",
                       "value": str(size), "hint": ""})
    except Exception:
        pass

    # 4) เซิร์ฟเวอร์หลังบ้าน: เดินมานานแค่ไหน (รีสตาร์ตบ่อย = มีอะไรพัง)
    uptime = (datetime.now(timezone.utc) - _STARTED_AT).total_seconds()
    checks.append({"key": "uptime", "label": "เซิร์ฟเวอร์หลังบ้านทำงานต่อเนื่อง",
                   "status": "ok" if uptime > 300 else "warn",
                   "value": _fmt_uptime(uptime),
                   "hint": "" if uptime > 300 else "เพิ่งรีสตาร์ตไปเมื่อครู่ ถ้ารีบ่อยผิดปกติให้ดู log ของ backend"})

    # 5) งานตามเวลา (แจ้งเตือนใกล้ครบกำหนด/เกินกำหนด) — ต้องมีจริงและมีรอบถัดไป
    try:
        from app.utils.scheduler import scheduler
        jobs = scheduler.get_jobs() if scheduler.running else []
        nxt = min((j.next_run_time for j in jobs if j.next_run_time), default=None)
        checks.append({
            "key": "scheduler", "label": "งานแจ้งเตือนอัตโนมัติ (ครบกำหนด/เกินกำหนด)",
            "status": "ok" if jobs else "error",
            "value": (f"{len(jobs)} งาน · รอบถัดไป {nxt:%d/%m/%Y %H:%M}" if nxt else
                      (f"{len(jobs)} งาน" if jobs else "ไม่ทำงาน")),
            "hint": "" if jobs else "ผู้ยืมจะไม่ได้รับแจ้งเตือนวันครบกำหนดเลย — ตรวจ log ตอนเริ่มเซิร์ฟเวอร์",
        })
    except Exception:  # pragma: no cover
        pass

    # 6) อีเมล: เปิดใช้จริงไหม (ปิดอยู่ = ผู้ใช้ยืนยันอีเมล/รีเซ็ตรหัสผ่านเองไม่ได้)
    email_on = settings.ENABLE_EMAIL and bool(settings.MAIL_USERNAME)
    checks.append({"key": "email", "label": "การส่งอีเมล",
                   "status": "ok" if email_on else "warn",
                   "value": "เปิดใช้งาน" if email_on else "ปิดอยู่ (โหมดพัฒนา)",
                   "hint": "" if email_on else "ลิงก์ยืนยันอีเมล/รีเซ็ตรหัสผ่านจะไม่ถูกส่งออกจริง"})

    # 7) คนกำลังใช้งานอยู่ (ประมาณจาก last_seen_at) + ใช้งานวันนี้
    now = datetime.now(timezone.utc)
    online = (await db.execute(select(func.count()).select_from(User).where(
        User.last_seen_at >= now - timedelta(minutes=ONLINE_WINDOW_MINUTES)))).scalar() or 0
    today = (await db.execute(select(func.count()).select_from(User).where(
        User.last_seen_at >= now - timedelta(hours=24)))).scalar() or 0
    checks.append({"key": "online_users", "label": f"ผู้ใช้ที่ใช้งานอยู่ ({ONLINE_WINDOW_MINUTES} นาทีล่าสุด)",
                   "status": "ok", "value": f"{online} คน · 24 ชม. ล่าสุด {today} คน", "hint": ""})

    # 8) พื้นที่ดิสก์ + ขนาดไฟล์แนบ (สาธารณะ/ส่วนตัว)
    try:
        usage = shutil.disk_usage(str(Path(settings.UPLOAD_DIR).resolve().parent))
        free_gb = round(usage.free / 1024 ** 3, 1)
        checks.append({"key": "disk", "label": "พื้นที่ดิสก์คงเหลือ",
                       "status": "ok" if free_gb >= DISK_WARN_FREE_GB else "warn",
                       "value": f"{free_gb} GB (ใช้ไป {round(usage.used / usage.total * 100)}%)",
                       "hint": "" if free_gb >= DISK_WARN_FREE_GB else "เหลือน้อย — ย้ายไฟล์แนบเก่าออกหรือขยายดิสก์"})
    except Exception:  # pragma: no cover
        pass
    checks.append({"key": "uploads", "label": "ขนาดไฟล์แนบ",
                   "status": "ok", "hint": "",
                   "value": f"รูป/ไฟล์สาธารณะ {_dir_size_mb(settings.UPLOAD_DIR)} MB · "
                            f"ใบยืมที่เซ็นแล้ว {_dir_size_mb(settings.PRIVATE_UPLOAD_DIR)} MB"})

    # 9) งานค้างที่ต้องมีคนทำ — ระบบ "ทำงานได้" แต่ถ้าไม่มีใครกดอนุมัติก็เท่ากับล่มสำหรับผู้ใช้
    pending_req = (await db.execute(select(func.count()).select_from(BorrowRequest)
                                    .where(BorrowRequest.status == "pending"))).scalar() or 0
    pending_users = (await db.execute(select(func.count()).select_from(User)
                                      .where(User.approval_status == "pending"))).scalar() or 0
    total_pending = pending_req + pending_users
    checks.append({"key": "queue", "label": "งานค้างรอเจ้าหน้าที่",
                   "status": "ok" if total_pending == 0 else "warn",
                   "value": f"คำขอยืม {pending_req} · ผู้สมัคร {pending_users}",
                   "hint": "" if total_pending == 0 else "มีคนรออยู่ — เข้าหน้าอนุมัติคำขอ/จัดการผู้ใช้"})
    checks.extend(await _performance_checks(db))
    return checks


# เกณฑ์ "ช้า" ของหน้าตรวจสอบระบบ — ผู้ใช้เริ่มรู้สึกหน่วงที่ราว 1 วินาทีต่อการกด 1 ครั้ง (หน้าเว็บยิงหลาย request)
API_P95_WARN_MS, API_P95_ERROR_MS = 800, 2500
LOOP_LAG_WARN_MS, LOOP_LAG_ERROR_MS = 100, 500
MEM_WARN_AVAILABLE_PCT = 10


def _status(value: float, warn: float, error: float) -> str:
    return "error" if value >= error else "warn" if value >= warn else "ok"


def _meminfo() -> dict[str, int]:
    """อ่าน /proc/meminfo (kB) — เครื่อง Prod เป็น Linux ใน container · ระบบอื่นคืน dict ว่างแล้วข้ามการ์ดนี้"""
    try:
        with open("/proc/meminfo") as f:
            return {k.strip(): int(v.split()[0]) for k, v in (line.split(":", 1) for line in f)}
    except (OSError, ValueError):
        return {}


def _process_rss_mb() -> float | None:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except (OSError, ValueError):
        pass
    return None


async def _performance_checks(db: AsyncSession) -> list[dict]:
    """ตัวชี้ว่า "ช้าเพราะอะไร" — แยกให้เห็นว่าคอขวดอยู่ที่แอป / event loop / ฐานข้อมูล / เครื่อง (1 ต.ค. 69)

    อาการหน่วงบน Prod มีสาเหตุได้หลายชั้นและแก้คนละวิธี: API ช้าเอง · loop ถูกบล็อก (worker เดียว) ·
    connection pool เต็ม · query ค้าง/รอ lock · CPU หรือ RAM ของ VM หมด — การ์ดแต่ละใบตอบทีละชั้น
    ส่วนชั้นเครือข่าย/nginx วัดจากฝั่งเบราว์เซอร์ (SystemCheckPage) เพราะเซิร์ฟเวอร์มองไม่เห็นเวลาที่เสียระหว่างทาง
    """
    checks: list[dict] = []
    p = perf.summary()

    # 1) ความเร็ว API จริงของทุกคนใน 5 นาทีล่าสุด
    st = _status(p["p95_ms"], API_P95_WARN_MS, API_P95_ERROR_MS) if p["count"] else "ok"
    checks.append({
        "key": "api_speed", "label": f"ความเร็ว API ({p['window_minutes']} นาทีล่าสุด)", "status": st,
        "value": (f"เฉลี่ย {p['avg_ms']:.0f} ms · 95% ไม่เกิน {p['p95_ms']:.0f} ms" if p["count"] else "ยังไม่มีข้อมูล"),
        "hint": (f"{p['count']} คำขอ ({p['per_minute']}/นาที) · ช้าสุด {p['max_ms']:.0f} ms · เกิน 1 วินาที {p['slow_over_1s']} ครั้ง"
                 + (" — ดูตาราง \"เส้นทางที่ช้าที่สุด\" ด้านล่าง" if st != "ok" else "")),
    })
    checks.append({
        "key": "api_errors", "label": f"ข้อผิดพลาดฝั่งเซิร์ฟเวอร์ ({p['window_minutes']} นาทีล่าสุด)",
        "status": "ok" if p["errors_5xx"] == 0 else "error",
        "value": f"{p['errors_5xx']} ครั้ง",
        "hint": "" if p["errors_5xx"] == 0 else "มี request ที่ตอบ 5xx — ดู log ของ backend (docker compose logs backend)",
    })

    # 2) event loop — worker เดียว ถ้างานใดไม่คืน loop ทุกคนค้างพร้อมกัน
    st = _status(p["loop_lag_max_ms"], LOOP_LAG_WARN_MS, LOOP_LAG_ERROR_MS)
    checks.append({
        "key": "event_loop", "label": "การตอบสนองของเซิร์ฟเวอร์ (event loop)", "status": st,
        "value": f"หน่วงสูงสุด {p['loop_lag_max_ms']:.0f} ms · เฉลี่ย {p['loop_lag_avg_ms']:.0f} ms",
        "hint": "" if st == "ok" else "มีงานที่ยึดเซิร์ฟเวอร์ไว้นานจนคำขอของคนอื่นต้องรอ (เช่น สร้าง PDF/นำเข้าไฟล์/ล็อกอินพร้อมกันหลายคน)",
    })

    # 3) connection pool ของแอป — เต็มแล้วคำขอถัดไปต้องรอคิวจนกว่าจะมีคนคืน
    pool = engine.pool
    try:
        in_use, size = pool.checkedout(), pool.size()
        overflow = max(0, pool.overflow())
        checks.append({
            "key": "db_pool", "label": "การเชื่อมต่อฐานข้อมูลของแอป (pool)",
            "status": "error" if overflow >= getattr(pool, "_max_overflow", 10) else "warn" if in_use >= size else "ok",
            "value": f"ใช้อยู่ {in_use} / {size} (ล้นเพิ่ม {overflow})",
            "hint": "" if in_use < size else "ใช้เต็ม pool — คำขอใหม่ต้องรอคิว ตรวจ query ที่ค้างหรือเพิ่ม pool_size",
        })
    except AttributeError:  # pragma: no cover - pool ชนิดที่ไม่มีตัวนับ (เช่น NullPool ตอนเทส)
        pass

    # 4) ฝั่ง PostgreSQL: จำนวน connection ทั้งเครื่อง + query ที่รันนานสุด + ที่รอ lock
    try:
        row = (await db.execute(text("""
            SELECT (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()),
                   current_setting('max_connections')::int,
                   coalesce((SELECT extract(epoch FROM max(now() - query_start)) FROM pg_stat_activity
                             WHERE datname = current_database() AND state = 'active' AND pid <> pg_backend_pid()), 0),
                   (SELECT count(*) FROM pg_stat_activity
                    WHERE datname = current_database() AND wait_event_type = 'Lock')
        """))).one()
        conns, max_conns, longest, waiting = int(row[0]), int(row[1]), float(row[2]), int(row[3])
        checks.append({
            "key": "db_connections", "label": "การเชื่อมต่อทั้งหมดที่ฐานข้อมูล",
            "status": "warn" if conns >= max_conns * 0.8 else "ok",
            "value": f"{conns} / {max_conns}",
            "hint": "" if conns < max_conns * 0.8 else "ใกล้เต็ม max_connections — มี process อื่นต่อค้างไว้หรือไม่",
        })
        busy = "error" if waiting or longest >= 30 else "warn" if longest >= 5 else "ok"
        checks.append({
            "key": "db_activity", "label": "คำสั่งที่ค้างในฐานข้อมูล", "status": busy,
            "value": f"นานสุด {longest:.1f} วินาที · รอ lock {waiting} รายการ",
            "hint": "" if busy == "ok" else "มี query รันนานหรือรอ lock กันอยู่ — ทุกหน้าที่แตะตารางเดียวกันจะช้าตาม",
        })
    except Exception:  # pragma: no cover - สิทธิ์อ่าน pg_stat_activity ถูกจำกัด
        pass

    # 5) เครื่อง: CPU (load average เทียบจำนวนคอร์) + RAM
    try:
        load1, load5, _ = os.getloadavg()
        cores = os.cpu_count() or 1
        checks.append({
            "key": "cpu_load", "label": "ภาระ CPU ของเครื่อง",
            "status": "error" if load5 >= cores * 2 else "warn" if load5 >= cores else "ok",
            "value": f"{load1:.2f} (1 นาที) · {load5:.2f} (5 นาที) / {cores} คอร์",
            "hint": "" if load5 < cores else "งานมากกว่าจำนวนคอร์ — ทุกอย่างบนเครื่องนี้จะช้าลงพร้อมกัน ตรวจว่า VM ได้ CPU พอหรือมีโปรแกรมอื่นแย่ง",
        })
    except OSError:  # pragma: no cover
        pass
    mem = _meminfo()
    if mem.get("MemTotal"):
        avail_pct = mem.get("MemAvailable", 0) / mem["MemTotal"] * 100
        swap_used_mb = (mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) / 1024
        rss = _process_rss_mb()
        low = avail_pct < MEM_WARN_AVAILABLE_PCT
        checks.append({
            "key": "memory", "label": "หน่วยความจำของเครื่อง",
            "status": "warn" if low or swap_used_mb > 256 else "ok",
            "value": f"ว่าง {mem.get('MemAvailable', 0) / 1024 / 1024:.1f} / {mem['MemTotal'] / 1024 / 1024:.1f} GB"
                     + (f" · แอปใช้ {rss:.0f} MB" if rss else ""),
            "hint": (f"ใช้ swap อยู่ {swap_used_mb:.0f} MB — " if swap_used_mb > 256 else "")
                    + ("RAM เหลือน้อย เครื่องจะเริ่มใช้ดิสก์แทน RAM ทำให้ช้าทั้งระบบ" if low or swap_used_mb > 256 else ""),
        })
    return checks
