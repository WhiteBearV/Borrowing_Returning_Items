FROM python:3.12-slim

WORKDIR /app
ENV HF_HOME=/models PYTHONUNBUFFERED=1

# torch แบบ CPU อย่างเดียว (~200 MB) — แบบปกติลาก CUDA มาด้วยหลาย GB ทั้งที่ VM ไม่มี GPU
RUN pip install --no-cache-dir torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# อบโมเดล (~3.5 GB) ลง image ตอน build — รันจริงไม่ต้องต่อเน็ต และ restart ไม่ต้องโหลดใหม่
ARG VISION_MODEL=google/siglip2-large-patch16-256
ENV VISION_MODEL=${VISION_MODEL}
RUN python -c "import os; from huggingface_hub import snapshot_download; snapshot_download(os.environ['VISION_MODEL'], allow_patterns=['*.json', '*.safetensors'])"
ENV HF_HUB_OFFLINE=1

COPY app.py .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
