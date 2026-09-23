import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# ชนิดลายเซ็น → คอลัมน์ที่เก็บชื่อไฟล์ (เฟส 11) — ประกาศที่นี่เพื่อให้ทั้ง model, service และ response
# ใช้ชุดเดียวกัน ห้ามเขียน mapping ซ้ำที่อื่น
SIGNATURE_FIELDS = {
    "handover_borrower": "handover_sig_borrower",
    "handover_staff": "handover_sig_staff",
    "return_borrower": "return_sig_borrower",
    "return_staff": "return_sig_staff",
}


class BorrowRequest(Base):
    __tablename__ = "borrow_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)  # REQ-2026-<student_id>-<hex6>
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending / approved / rejected / cancelled / completed
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # เหตุผลที่ "ผู้ยืม" ยกเลิกเอง — แยกจาก rejection_reason (ของแอดมิน) คนละคนคนละเหตุผล
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # วันที่นักศึกษาขอคืนเอง ระบุตอนยื่นคำขอ — เพดานสูงสุด MAX_REQUESTED_DUE_DATE_YEARS
    # (ดู borrow_service.py) กันพิมพ์ผิดหลุดเข้าระบบ แอดมินยังใช้ดุลพินิจตอนอนุมัติ/ปฏิเสธได้ตามปกติ
    requested_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    is_overdue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ผู้รับคืน = admin ที่กดรับคืนล่าสุด (ใบคืนต้องระบุว่าใครรับของมา)
    # ponytail: เก็บระดับคำขอ ถ้าต้องรู้ว่าแต่ละชิ้นใครรับ ค่อยย้ายไป borrow_items.received_by
    returned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # นัดรับของ (เฟส 4) — ตั้งตอนอนุมัติ เว้นว่างได้ = จ่ายทันทีหน้าเคาน์เตอร์ ไม่ได้นัดล่วงหน้า
    # อยู่ระดับคำขอเพราะจ่ายของทั้งใบพร้อมกันในนัดเดียว (ต่างจากนัดคืนที่อยู่รายชิ้น)
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pickup_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pickup_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ใบยืมที่ผู้ยืมเซ็นแล้วอัปโหลดกลับเข้ามา (ทางเลือกแทนการปริ้นถือมา)
    # เก็บ **ชื่อไฟล์เปล่า** ในโฟลเดอร์ PRIVATE_UPLOAD_DIR ที่ไม่ได้เสิร์ฟสาธารณะ — ไฟล์มีลายเซ็น+ชื่อ+รหัส นศ.
    # เปิดได้ทางเดียวคือ GET /borrow-requests/{id}/signed-form ที่ตรวจสิทธิ์ก่อน (เฟส 7)
    signed_form_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    signed_form_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # จ่ายของจริง (เฟส 11) — บันทึกการส่งมอบเท่านั้น ไม่ใช่สถานะใหม่ สต็อกยังตัดตอนอนุมัติเหมือนเดิม
    handover_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handover_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # ลายเซ็นบนหน้าจอ — เก็บ **ชื่อไฟล์ PNG เปล่า** ใน PRIVATE_UPLOAD_DIR เหมือน signed_form_file
    # เปิดได้ทางเดียวคือ GET /borrow-requests/{id}/signature/{kind} ที่ตรวจสิทธิ์ก่อน
    handover_sig_borrower: Mapped[str | None] = mapped_column(String(500), nullable=True)
    handover_sig_staff: Mapped[str | None] = mapped_column(String(500), nullable=True)
    return_sig_borrower: Mapped[str | None] = mapped_column(String(500), nullable=True)
    return_sig_staff: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # หลักฐานประกอบการเซ็นแต่ละครั้ง (เวลา ผู้เกี่ยวข้อง user-agent sha256) — ใช้ยืนยันว่าไฟล์ไม่ถูกสลับ
    signature_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    student = relationship("User", foreign_keys=[student_id], back_populates="borrow_requests_as_student")
    approver = relationship("User", foreign_keys=[approved_by], back_populates="borrow_requests_as_approver")
    receiver = relationship("User", foreign_keys=[returned_by])
    # selectin เสมอ: handover_by_name ถูกอ่านตอน serialize ทุก response (รายการ/แจ้งเตือน/PDF) — lazy-load ใน
    # async = MissingGreenlet → 500 ทั้งหน้าทันทีที่มีคำขอที่จ่ายของแล้วอยู่ในรายการ (เจอจริง 23 ก.ย.)
    handover_staff = relationship("User", foreign_keys=[handover_by], lazy="selectin")
    items = relationship("BorrowItem", back_populates="borrow_request", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="borrow_request")

    __table_args__ = (Index("ix_borrow_requests_status", "status"),)

    @property
    def handover_by_name(self) -> str | None:
        """ชื่อเจ้าหน้าที่ที่จ่ายของ — ใบยืมและหน้าเว็บต้องบอกได้ว่าใครเป็นคนส่งมอบ"""
        return self.handover_staff.full_name if self.handover_staff else None

    @property
    def signatures(self) -> list[str]:
        """ชนิดลายเซ็นที่มีแล้ว เช่น ["handover_borrower"] — ส่งให้หน้าเว็บแทนชื่อไฟล์จริง

        ชื่อไฟล์เป็นข้อมูลภายใน ไม่ควรหลุดออก response (เปิดดูต้องผ่าน endpoint ที่ตรวจสิทธิ์อยู่แล้ว)
        """
        return [kind for kind, field in SIGNATURE_FIELDS.items() if getattr(self, field, None)]

    @property
    def student_name(self) -> str | None:
        return self.student.full_name if self.student else None

    @property
    def student_email(self) -> str | None:
        return self.student.email if self.student else None

    @property
    def student_number(self) -> str | None:
        return self.student.student_id if self.student else None

    @property
    def borrower_identifier(self) -> str | None:
        """รหัสประจำตัวที่พิมพ์ลงใบยืม — นักศึกษาใช้รหัสนักศึกษา อาจารย์/เจ้าหน้าที่ใช้ username
        (student_number คงความหมายเดิมคือ "รหัสนักศึกษา" เท่านั้น ห้ามเอาสองอันมาปนกัน)
        """
        if not self.student:
            return None
        return self.student.student_id or self.student.username

    @property
    def borrower_is_student(self) -> bool:
        """ใช้เลือกคำว่า "นักศึกษา" หรือ "อาจารย์/เจ้าหน้าที่" บนฟอร์ม"""
        return bool(self.student and self.student.student_id)

    @property
    def student_major(self) -> str | None:
        return self.student.major if self.student else None

    @property
    def student_year_label(self) -> str | None:
        """ป้ายชั้นปีผู้ยืมสำหรับหน้าอนุมัติคำขอ เช่น "ปีที่ 2" / "ตกค้าง (ปีที่ 5)" / "บุคลากร"

        คำนวณผ่าน app.utils.study_year (จุดเดียว) — property นี้เป็น sync ไม่มี DB session ให้อ่าน setting
        `academic_year_start` ที่แอดมินปรับได้เอง จึง**ต้องมีคนเติมค่าที่ผ่าน setting จริงมาก่อน** ผ่าน setter
        ด้านล่าง (ดู borrow_service.list_requests/get_request ที่เรียก users_service.attach_study_year() แล้ว
        เซ็ตกลับมาที่นี่) — ถ้าไม่มีใครเติม fallback ไปใช้ค่าเริ่มต้น (1 มิ.ย.) เหมือนเดิม เพื่อไม่ให้ response
        เก่าที่ยังไม่ได้แก้ (หรือเทสที่สร้าง BorrowRequest ตรง ๆ ไม่ผ่าน service) พังไปเลย
        (แก้ตามรีวิวรอบ 2 — เดิมใช้ค่าเริ่มต้นเสมอ ไม่เคยสะท้อน setting จริงเลยสักครั้ง)
        """
        override = getattr(self, "_student_year_label_override", None)
        if override is not None:
            return override
        if not self.student:
            return None
        from app.utils.study_year import compute_study_year
        # role != "student" ถือเป็นบุคลากรเสมอ (กฎเดียวกับ users_service.attach_study_year — ดูที่นั่น)
        # แม้ enrollment_year จะยังค้างอยู่จากตอนเป็นนักศึกษาก่อนถูกเลื่อนสิทธิ์เป็น admin/superadmin
        # (แก้ตามรีวิวรอบ 3, MINOR-1 — เดิม fallback นี้ไม่เช็ค role เลย โชว์ "ปีที่ 4" ผิดๆ ให้แอดมิน)
        enrollment_year = self.student.enrollment_year if self.student.role == "student" else None
        return compute_study_year(enrollment_year, self.student.study_years or 4).label

    @student_year_label.setter
    def student_year_label(self, value: str | None) -> None:
        self._student_year_label_override = value

    @property
    def approver_name(self) -> str | None:
        return self.approver.full_name if self.approver else None

    @property
    def receiver_name(self) -> str | None:
        return self.receiver.full_name if self.receiver else None
