"""บริการแปลงรูป/ข้อความเป็นเวกเตอร์ (SigLIP2) สำหรับ "ค้นหาอุปกรณ์ด้วยรูป"

แยก container จาก backend: โมเดลกิน RAM ~3.5 GB + CPU หนัก — ล่ม/ช้าแล้วระบบยืมไม่ล่มตาม
อยู่ในเครือข่ายภายในของ compose เท่านั้น (ไม่เปิด port) ผู้เรียกมีแค่ backend ที่ตรวจไฟล์มาแล้ว
ไม่เก็บอะไรลงดิสก์ — รูปของผู้ใช้อยู่ใน RAM ระหว่างคำนวณเท่านั้น
"""
import io
import os
import threading

import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel, Field
from transformers import AutoModel, AutoProcessor

MODEL = os.environ.get("VISION_MODEL", "google/siglip2-large-patch16-256")
# กันรูประเบิด (ไฟล์ PNG เล็กแต่ภาพหลายหมื่นพิกเซล ถอดแล้วกิน RAM/CPU หลาย GB) — ภาพมือถือ 48MP ยังผ่าน
Image.MAX_IMAGE_PIXELS = 50_000_000
MAX_SIDE = 1024  # โมเดลใช้แค่ 256px ย่อก่อน convert ให้ถอดรูปเบาลง
torch.set_num_threads(int(os.environ.get("VISION_THREADS", "2")))

proc = AutoProcessor.from_pretrained(MODEL)
model = AutoModel.from_pretrained(MODEL).eval()
# ponytail: คำนวณทีละคำขอ — 2 คำขอพร้อมกันบน 2 vCPU แย่ง thread กันจนช้าทั้งคู่ คิวรอดีกว่า
_lock = threading.Lock()

app = FastAPI(title="vision")

# อุ่นเครื่องตอนบูต — ครั้งแรกที่คำนวณช้า ~6 วิ (โหลด weight จริงเข้า RAM) ไม่ให้ผู้ใช้คนแรกต้องรอ
with torch.no_grad():
    model.get_image_features(**proc(images=[Image.new("RGB", (256, 256))], return_tensors="pt"))


def _vec(out) -> list[list[float]]:
    f = getattr(out, "pooler_output", out)
    return torch.nn.functional.normalize(f, dim=-1).tolist()


def prompt(text: str) -> str:
    """ข้อความแบบที่ SigLIP2 ฝึกมา — ต้องเป็นตัวพิมพ์เล็ก (PoC: ไม่ lower ได้ top-5 25%, lower ได้ 95%)"""
    return f"this is a photo of {text.strip()}.".lower()


class TextsIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=64)


@app.get("/health")
def health() -> dict:
    return {"model": MODEL}


@app.post("/embed/image")
def embed_image(file: UploadFile = File(...)) -> dict:
    """รูป 1 รูป → เวกเตอร์ (normalize แล้ว) · def ธรรมดา = FastAPI รันใน threadpool ไม่บล็อก event loop"""
    try:
        img = Image.open(io.BytesIO(file.file.read()))  # อ่านแค่หัวไฟล์ — เกิน MAX_IMAGE_PIXELS โยน error ที่นี่
        if img.width * img.height > Image.MAX_IMAGE_PIXELS:
            raise ValueError("image too large")
        img.draft("RGB", (MAX_SIDE, MAX_SIDE))  # JPEG: ถอดที่ความละเอียดต่ำตั้งแต่แรก
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        img = img.convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Invalid image: {e}") from e
    with _lock, torch.no_grad():
        v = _vec(model.get_image_features(**proc(images=[img], return_tensors="pt")))[0]
    return {"model": MODEL, "vector": v}


@app.post("/embed/text")
def embed_text(body: TextsIn) -> dict:
    """ชื่ออุปกรณ์หลายชื่อ → เวกเตอร์ · padding max_length=64 ตามตอนฝึก ไม่งั้นเวกเตอร์เพี้ยน"""
    with _lock, torch.no_grad():
        out = model.get_text_features(**proc(text=[prompt(t) for t in body.texts], padding="max_length",
                                             max_length=64, truncation=True, return_tensors="pt"))
    return {"model": MODEL, "vectors": _vec(out)}
