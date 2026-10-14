FROM python:3.12-slim

WORKDIR /app

# นาฬิกาของ container เป็น UTC โดยปริยาย — date.today() ทั่วโค้ดจะได้วันของ UTC ช่วง 00:00–07:00 น.
# เวลาไทยจึงเป็น "เมื่อวาน" (เช่น job ตรวจเกินกำหนดที่ยิงเที่ยงคืนไทยเทียบกับวันเมื่อวาน ทวงช้าไป 1 วัน)
# image มี tzdata อยู่แล้ว (/usr/share/zoneinfo/Asia/Bangkok)
ENV TZ=Asia/Bangkok

# OCR นำเข้าทะเบียนจากรูป/PDF (โหมดทดลอง) — tesseract + ภาษาไทย, poppler ไว้แปลง PDF เป็นรูป
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-tha poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# ติดตั้งจากไฟล์ล็อก (เวอร์ชันเดียวกับที่ผ่านเทส) ไม่ใช่ requirements.txt ที่เป็น >= — ไม่งั้น build ใหม่ได้ไลบรารีรุ่นที่ไม่เคยทดสอบ
# (30 ก.ย. 69 ได้ SQLAlchemy 2.1 ที่ไม่ติดตั้ง greenlet ให้ → backend import ไม่ผ่าน ระบบล่ม)
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
