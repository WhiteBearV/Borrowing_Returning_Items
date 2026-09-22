"""ระดับสิทธิ์ในระบบ — 3 ระดับตาม feedback อาจารย์ 5 ก.ย. 69

| role         | คือใคร                    | ทำอะไรได้เพิ่มจากระดับล่าง                                  |
|--------------|---------------------------|-------------------------------------------------------------|
| `student`    | นักศึกษา/ผู้ยืมทั่วไป      | ยืม/ขอคืน/ขอต่อเวลาของตัวเอง                                 |
| `admin`      | ผู้ดูแลคลัง (AdminStore)   | จัดการอุปกรณ์ · อนุมัติ-รับคืน · นำเข้าไฟล์ทะเบียน            |
| `superadmin` | ผู้ดูแลระบบสูงสุด          | แก้ settings · ลบถาวร (อุปกรณ์/ผู้ใช้/ประวัติ) · เปลี่ยน role  |

เก็บเป็น string ในคอลัมน์ `users.role` เหมือนเดิม ไม่ทำ Enum ที่ DB — เพิ่มระดับใหม่ทีหลัง
จะได้ไม่ต้อง migrate type (ระบบเล็ก ผู้ใช้ ~300 คน ค่าที่รับได้ถูกบังคับที่ชั้น service อยู่แล้ว)

**สำคัญ:** ทุกที่ที่เคยเขียน `role == "admin"` ต้องใช้ `is_staff()` แทน ไม่งั้น superadmin
จะกลายเป็นสิทธิ์ *น้อยกว่า* admin (เช่น ไม่ได้รับแจ้งเตือนคำขอใหม่ หรือดูคำขอคนอื่นไม่ได้)
"""
from app.models.user import User

STUDENT = "student"
ADMIN = "admin"
SUPERADMIN = "superadmin"

# ทุก role ที่ถือว่าเป็น "เจ้าหน้าที่" — ใช้ทั้งเช็คสิทธิ์และ query หาคนที่ต้องรับแจ้งเตือน
STAFF_ROLES = (ADMIN, SUPERADMIN)
ALL_ROLES = (STUDENT, ADMIN, SUPERADMIN)

ROLE_LABEL_TH = {
    STUDENT: "ผู้ใช้งาน",
    ADMIN: "ผู้ดูแลคลัง",
    SUPERADMIN: "ผู้ดูแลระบบสูงสุด",
}


def is_staff(user: User) -> bool:
    """เป็นเจ้าหน้าที่ (ผู้ดูแลคลังหรือสูงกว่า) หรือไม่"""
    return user.role in STAFF_ROLES


def is_superadmin(user: User) -> bool:
    return user.role == SUPERADMIN


# ลำดับยศ — ใช้ตัดสินว่าใครจัดการบัญชีใครได้ (can_manage_user) และสร้างบัญชียศไหนได้
ROLE_RANK = {STUDENT: 0, ADMIN: 1, SUPERADMIN: 2}


def role_rank(role: str) -> int:
    return ROLE_RANK.get(role, 0)


def can_manage_user(actor: User, target: User) -> bool:
    """จัดการบัญชีคนอื่น (เปิด/ปิด · อนุมัติผู้สมัคร · แก้ชั้นปี) ได้เฉพาะบัญชีที่ยศ **ต่ำกว่า** ตัวเอง
    superadmin จัดการได้ทุกคน — **จุดเดียว** ที่ตัดสินเรื่องนี้ (หน้าเว็บมีคู่แฝดใน utils/role.js ไว้ซ่อนปุ่ม)

    22 ก.ย. 69 เจอจริง: endpoint เหล่านี้กั้นแค่ require_admin แต่ไม่ดูยศของบัญชีเป้าหมาย ผู้ดูแลคลังปิดบัญชี
    superadmin ได้ (ใช้งานไม่ได้ทันทีเพราะ get_current_user เช็ค is_active และไม่มีใครยศสูงพอจะเปิดคืน)
    ผู้ดูแลคลังด้วยกันก็จัดการกันเองไม่ได้ — กันคนเดียวปิดบัญชีเจ้าหน้าที่คนอื่นทั้งหมด ต้องให้ superadmin ทำ
    """
    return is_superadmin(actor) or role_rank(target.role) < role_rank(actor.role)
