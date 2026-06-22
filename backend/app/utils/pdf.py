import io
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_borrow_pdf(borrow_request: object) -> bytes:
    """สร้าง PDF ใบยืมอุปกรณ์ด้วย ReportLab"""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("ใบยืมอุปกรณ์ / Equipment Borrow Request", styles["Title"]))
    elements.append(Spacer(1, 12))

    req = borrow_request
    elements.append(Paragraph(f"รหัสคำขอ: {getattr(req, 'request_code', '-')}", styles["Normal"]))
    elements.append(Paragraph(f"วันที่ยื่นคำขอ: {getattr(req, 'requested_at', datetime.now())}", styles["Normal"]))
    elements.append(Paragraph(f"วัตถุประสงค์: {getattr(req, 'purpose', '-')}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    # TODO: เพิ่มตารางรายการอุปกรณ์, ข้อมูลผู้ยืม, ลายเซ็น

    doc.build(elements)
    return buf.getvalue()
