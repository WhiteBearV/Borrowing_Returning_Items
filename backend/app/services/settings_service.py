import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting
from app.models.user import User
from app.services import audit_service
from app.utils.roles import is_superadmin

# ค่าที่ผู้ดูแลคลังแก้เองได้ — งานหน้าเคาน์เตอร์ล้วน ๆ ไม่กระทบตัวเลขเงินหรือข้อมูลย้อนหลัง
# ที่เหลือ (ค่าปรับ · ค่าเสื่อม · มูลค่าที่พิมพ์ในใบยืม) ยังเป็นของ superadmin เพราะกระทบยอดที่เรียกเก็บ
# และตัวเลขในเอกสารเก่า — ตกลงกับผู้ใช้ไว้ 8 ก.ย. 69
ADMIN_EDITABLE_KEYS = {
    "default_pickup_location",
    "default_pickup_time",
    "due_soon_notify_days_before",
    "low_stock_threshold_default",
    "max_items_per_request",
    "max_active_requests_per_student",
    "max_renew_count",
    "max_renew_days",
}


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
    await db.refresh(setting)
    return setting
