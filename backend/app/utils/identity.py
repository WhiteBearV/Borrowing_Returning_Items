"""รหัสประจำตัวผู้ใช้ที่เอาไปแสดง/อ้างอิง — นักศึกษาใช้ student_id, อาจารย์/เจ้าหน้าที่ใช้ username

เดิมมีตรรกะนี้กระจายอยู่ 2 ที่แล้ว fallback ไม่ตรงกัน (borrow_service._ident ลงท้ายด้วย "USER",
audit_service.log_action ลงท้ายด้วย email) รวมมาไว้ที่เดียวเพื่อให้เลขคำขอกับ audit log อ่านตรงกัน
"""
from app.models.user import User


def user_identifier(user: User) -> str:
    """รหัสที่ใช้แทนตัวคนนี้ — ไม่มีทั้ง student_id/username ก็ยังต้องได้ค่าที่ไม่ซ้ำกับคนอื่น

    บัญชีที่สร้างจาก scripts/create_admin.py ไม่มีทั้งคู่ ถ้า fallback เป็นค่าคงที่ ("USER") เลขคำขอ
    ของแอดมิน 2 คนจะชนกันจริง (borrow_requests.request_code เป็น unique) แล้วคนที่สองยื่นคำขอไม่ได้เลย
    — ใช้ 8 ตัวแรกของ uuid แทน ได้ค่าคงที่ต่อคนและไม่ซ้ำกัน
    """
    return user.student_id or user.username or user.id.hex[:8].upper()


def is_student_identifier(value: str | None) -> bool:
    """รหัสนักศึกษา = ตัวเลข 10 หลักล้วน — ใช้กันไม่ให้ username ของอาจารย์ไปซ้ำรูปแบบเดียวกัน
    (login รับได้ทั้ง student_id/username/email ถ้าซ้ำรูปแบบกันจะแยกไม่ออกว่าหมายถึงใคร)
    """
    return bool(value) and value.isdigit() and len(value) == 10
