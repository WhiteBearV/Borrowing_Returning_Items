"""
สร้างบัญชีแอดมิน — ใช้ตอนติดตั้งระบบครั้งแรก

จำเป็นต้องมีสคริปต์นี้เพราะไม่มีทางสร้างแอดมินคนแรกผ่าน API ได้เลย:
POST /users เป็น endpoint เดียวที่รับ role แต่ถูกกั้นด้วย require_admin
ส่วน POST /auth/register ไม่มีฟิลด์ role ทุกคนที่สมัครเองจึงเป็น student เสมอ

    python scripts/create_admin.py                        # ถามทีละข้อ
    python scripts/create_admin.py admin@cdti.ac.th 'ชื่อ นามสกุล'   # ส่งมาเลย
    python scripts/create_admin.py --superadmin boss@cdti.ac.th 'ชื่อ นามสกุล'  # ผู้ดูแลระบบสูงสุด

ถ้ามีอีเมลนี้อยู่แล้วจะเลื่อนขั้นให้แทนการสร้างใหม่
(เผื่อกรณีสมัครผ่านหน้าเว็บไปก่อนแล้วเพิ่งนึกได้ว่าต้องเป็นแอดมิน)

**ผู้ดูแลระบบสูงสุด (superadmin) คนแรกต้องสร้างด้วยสคริปต์นี้เท่านั้น** — endpoint เปลี่ยน role
ถูกกั้นด้วย require_superadmin จึงต้องมีคนแรกอยู่ก่อนถึงจะตั้งคนต่อไปผ่านหน้าเว็บได้

รันใน docker:
    docker compose -f docker-compose.prod.yml exec backend python scripts/create_admin.py
"""
import asyncio
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User


async def create_admin(
    email: str, full_name: str, password: str, username: str = "", role: str = "admin"
) -> None:
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing:
            existing.role = role
            existing.email_verified = True
            existing.is_active = True
            existing.password_hash = hash_password(password)
            await db.commit()
            print(f"อัปเดตบัญชีเดิม {email} เป็น {role} แล้ว")
            return

        db.add(User(
            email=email,
            full_name=full_name,
            # รหัสประจำตัว (เช่น 01MNK01) — ไม่บังคับ แต่ควรใส่: ไม่มีทั้ง student_id/username แล้ว
            # เลขคำขอยืมจะ fallback ไปใช้ uuid ซึ่งอ่านไม่รู้เรื่องบนเอกสาร (ดู utils/identity.py)
            username=username or None,
            password_hash=hash_password(password),
            role=role,
            # แอดมินสร้างจากเครื่อง server อยู่แล้ว ไม่ต้องยืนยันอีเมลซ้ำ
            # (และถ้า SMTP ยังไม่พร้อม จะติดล็อกเข้าระบบไม่ได้เลย)
            email_verified=True,
            is_active=True,
        ))
        await db.commit()
        print(f"สร้างบัญชี {role} {email} เรียบร้อย")


def main() -> None:
    args = sys.argv[1:]
    # --superadmin = ผู้ดูแลระบบสูงสุด (แก้ settings/ลบถาวร/เปลี่ยนสิทธิ์ได้) ดู app/utils/roles.py
    role = "superadmin" if "--superadmin" in args else "admin"
    args = [a for a in args if a != "--superadmin"]
    sys.argv = [sys.argv[0], *args]
    email = sys.argv[1] if len(sys.argv) > 1 else input("อีเมล: ").strip()
    full_name = sys.argv[2] if len(sys.argv) > 2 else input("ชื่อ-นามสกุล: ").strip()
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("รหัสผ่าน (อย่างน้อย 8 ตัว): ")
    username = (sys.argv[3] if len(sys.argv) > 3
                else input("รหัสประจำตัวอาจารย์/เจ้าหน้าที่ เช่น 01MNK01 (เว้นว่างได้): ")).strip()

    if not email or not full_name:
        sys.exit("ต้องระบุอีเมลและชื่อ-นามสกุล")
    # ให้ตรงกับที่ schemas/auth.py บังคับไว้ ไม่งั้นจะสร้างบัญชีที่ตั้งรหัสผ่านใหม่ผ่านเว็บไม่ได้
    if len(password) < 8:
        sys.exit("รหัสผ่านต้องยาวอย่างน้อย 8 ตัวอักษร")

    asyncio.run(create_admin(email, full_name, password, username, role))


if __name__ == "__main__":
    main()
