FROM python:3.12-slim

WORKDIR /app

# OCR นำเข้าทะเบียนจากรูป/PDF (โหมดทดลอง) — tesseract + ภาษาไทย, poppler ไว้แปลง PDF เป็นรูป
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-tha poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
