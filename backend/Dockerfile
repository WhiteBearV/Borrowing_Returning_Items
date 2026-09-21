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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
