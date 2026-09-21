import re
import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting
from app.models.user import User
from app.services import audit_service
from app.utils.roles import is_superadmin
from app.utils.scheduler import reschedule_daily_jobs
from app.utils.study_year import DEFAULT_ACADEMIC_YEAR_START

# ค่าที่ผู้ดูแลคลังแก้เองได้ — งานหน้าเคาน์เตอร์ล้วน ๆ ไม่กระทบตัวเลขเงินหรือข้อมูลย้อนหลัง
# ที่เหลือ (ค่าปรับ · ค่าเสื่อม · มูลค่าที่พิมพ์ในใบยืม) ยังเป็นของ superadmin เพราะกระทบยอดที่เรียกเก็บ
# และตัวเลขในเอกสารเก่า — ตกลงกับผู้ใช้ไว้ 8 ก.ย. 69
# ค่าคุณภาพ (เฟส 10, 15 ก.ย. 69): quality_repair_default_drop/quality_low_threshold/academic_year_start
# เป็นงานหน้าเคาน์เตอร์เหมือนกัน (ค่าที่เสนอตอนซ่อม/เกณฑ์เตือน/วันเลื่อนชั้นปี) ผู้ดูแลคลังแก้ได้
# ส่วน quality_age_weight/quality_life_years_default กระทบสูตรคำนวณค่าคุณภาพย้อนหลังทุกเครื่อง = superadmin เท่านั้น
ADMIN_EDITABLE_KEYS = {
    "default_pickup_location",
    "default_pickup_time",
    "due_soon_notify_days_before",
    "low_stock_threshold_default",
    "max_items_per_request",
    "max_active_requests_per_student",
    "max_renew_count",
    "max_renew_days",
    "quality_repair_default_drop",
    "quality_low_threshold",
    "academic_year_start",
}


def _validate_setting_value(key: str, value: str) -> None:
    """ตรวจค่าก่อนบันทึก — เฉพาะคีย์ที่พิมพ์ผิดแล้วพังทั้งระบบเงียบ ๆ (สูตรคุณภาพ/วันเลื่อนชั้นปี)
    คีย์อื่นที่ไม่อยู่ในนี้ปล่อยผ่าน (ของเดิมก็ไม่เคยตรวจอะไรเลย ไม่ขยายขอบเขตเกินความจำเป็น)
    """
    def _num(v: str) -> float:
        try:
            return float(v)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"ค่า '{key}' ต้องเป็นตัวเลข")

    if key == "quality_age_weight":
        n = _num(value)
        if not (0 <= n <= 100):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="น้ำหนักอายุต้องอยู่ระหว่าง 0-100")
    elif key == "quality_life_years_default":
        # ต้องเป็นจำนวนเต็มเท่านั้น — แม้ตัวอ่านค่า (equipment_service.quality_settings() ผ่าน _safe_int())
        # จะกันพังด้วย fallback เป็นค่าเริ่มต้นอยู่แล้วตั้งแต่รีวิวรอบ 2 (M3, ไม่ throw 500 อีกต่อไปแม้ค่าใน
        # DB เพี้ยนไปแล้ว เช่นถูกแก้ตรงผ่าน SQL ข้าม validate นี้) แต่ยังตรวจที่จุดเขียนนี้เพื่อไม่ให้ค่าเพี้ยน
        # (เช่น "4.5") หลุดเข้า DB ตั้งแต่แรกผ่านช่องทางปกติ — กันไว้ดีกว่าต้องพึ่ง fallback ทุกครั้งที่อ่าน
        # (แก้คำอธิบายให้ตรงกับพฤติกรรมจริงตามรีวิวรอบ 3, MINOR-12)
        if not re.fullmatch(r"\d+", (value or "").strip()):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="อายุการใช้งานกลางต้องเป็นจำนวนเต็มปี (ไม่มีทศนิยม)")
        if int(value) < 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="อายุการใช้งานกลางต้องอย่างน้อย 1 ปี")
    elif key == "quality_repair_default_drop":
        n = _num(value)
        if not (0 <= n <= 100):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ค่าที่เสนอตอนซ่อมต้องอยู่ระหว่าง 0-100")
    elif key == "quality_low_threshold":
        n = _num(value)
        if not (0 <= n <= 100):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="เกณฑ์คุณภาพต่ำต้องอยู่ระหว่าง 0-100")
    elif key == "academic_year_start":
        # ต้องเป็นวันที่จริงในปฏิทิน ไม่ใช่แค่ตัวเลขอยู่ในช่วงกว้าง ๆ — regex เดิม (01-31 ทุกเดือน) ปล่อยให้
        # "02-30"/"02-31" (กุมภาพันธ์ไม่มีวันนี้) ผ่านได้ทั้งที่ parse เป็นวันที่จริงไม่ขึ้น ใช้ปี 2024
        # (ปีอธิกสุรทิน) เป็นปีอ้างอิงเพื่อให้ 29 ก.พ. ยังผ่านด้วย — ปีการศึกษาเวียนซ้ำทุกปีอยู่แล้ว ปีอ้างอิง
        # ไม่มีผลอะไรนอกจากใช้ตรวจความถูกต้องของวันที่ (deviation ที่ตกลงกันตอนรีวิวรอบ 2)
        try:
            datetime.strptime(f"2024-{value}", "%Y-%m-%d")
        except (ValueError, TypeError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="วันที่เริ่มปีการศึกษาต้องอยู่ในรูปแบบ MM-DD และเป็นวันที่จริง เช่น 06-01")
    elif key == "notify_time":
        # ค่าเพี้ยนตรงนี้ = job แจ้งเตือนรายวันเลื่อนไปผิดเวลาเงียบ ๆ (หรือถอยไปค่าเริ่มต้นตอนบูต)
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value or ""):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="เวลาส่งแจ้งเตือนต้องอยู่ในรูปแบบ HH:MM (24 ชั่วโมง) เช่น 08:00")


async def get_academic_year_start(db: AsyncSession) -> str:
    """อ่านค่า setting วันเริ่มปีการศึกษา (MM-DD) — **จุดเดียว** ที่อ่านคีย์นี้จาก DB

    เดิมมี helper ชื่อคนละชื่อทำแบบเดียวกันเป๊ะซ้ำอยู่ 4 ที่ (equipment_service._academic_year_start /
    users_service._academic_year_start / auth_service.study_year_preview / dashboard_service.get_summary)
    เสี่ยงแก้ค่า default หรือ fallback ที่เดียวแล้วลืมอีกที่ — ทุกจุดต้องเรียกจากที่นี่แทน (พบตอนรีวิวรอบ 2)
    """
    row = (await db.execute(select(Setting.value).where(Setting.key == "academic_year_start"))).scalar_one_or_none()
    return row or DEFAULT_ACADEMIC_YEAR_START


async def list_settings(db: AsyncSession) -> list[Setting]:
    result = await db.execute(select(Setting).order_by(Setting.key))
    return list(result.scalars().all())


async def update_setting(db: AsyncSession, admin: User, key: str, value: str) -> Setting:
    """แก้ค่า setting — บันทึก audit ด้วยเพราะค่าเหล่านี้ (โควตา/ค่าเสื่อม/ค่าปรับ) กระทบทั้งระบบย้อนหลัง
    ต้องตอบได้ว่าใครเปลี่ยนจากเท่าไหร่เป็นเท่าไหร่เมื่อไหร่ ไม่ใช่เห็นแค่ค่าปัจจุบัน"""
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Setting '{key}' not found.")
    if key not in ADMIN_EDITABLE_KEYS and not is_superadmin(admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ค่านี้แก้ได้เฉพาะผู้ดูแลระบบสูงสุด (เกี่ยวกับค่าปรับ/ค่าเสื่อม/เอกสารย้อนหลัง)")
    _validate_setting_value(key, value)
    old_value = setting.value
    setting.value = value
    if old_value != value:
        # settings ใช้ key เป็น PK ไม่มี UUID — audit_logs.target_id เป็น UUID NOT NULL จึงใช้ uuid5
        # ที่ derive จาก key เพื่อให้ log ของ setting เดียวกันมี target_id เดิมเสมอ (กรองประวัติรายค่าได้)
        await audit_service.log_action(
            db, admin, "update_setting", "settings",
            uuid.uuid5(uuid.NAMESPACE_OID, f"setting:{key}"),
            # เก็บคำอธิบายภาษาไทยลงไปด้วย — หน้า audit จะได้เขียนเป็นประโยคที่คนอ่านรู้เรื่อง
            # โดยไม่ต้องรู้จัก key ดิบอย่าง max_active_requests_per_student
            {"setting": key, "setting_label": setting.description or key,
             "changes": {key: [old_value, value]}},
        )
    await db.commit()
    if key == "notify_time" and old_value != value:
        reschedule_daily_jobs(value)  # หลัง commit — ถ้าบันทึกไม่ผ่าน job ต้องไม่เลื่อนไปก่อน
    await db.refresh(setting)
    return setting
