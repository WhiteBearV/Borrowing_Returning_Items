import io

import qrcode
from PIL import Image


def generate_qr_png(code: str) -> bytes:
    """สร้าง QR Code จากรหัสอุปกรณ์ คืนเป็น PNG bytes"""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(code)
    qr.make(fit=True)
    img: Image.Image = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
