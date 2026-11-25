"""ค้นหาอุปกรณ์ด้วยรูป (25 พ.ย. 69) — ผู้ยืมถ่ายรูปของ → 5 รุ่นในคลังที่ใกล้ที่สุด

โมเดล SigLIP2 รันใน container `vision` (vision/app.py) backend แค่ส่งรูป/ข้อความไปขอเวกเตอร์
คะแนนต่อรุ่น = max(z-score ของรูปถ่าย↔รูปในคลัง, z-score ของรูปถ่าย↔ชื่อรุ่น) — PoC ได้ top-5 97%
(Plans/2026-11-25-image-search/poc-results.md) · ครุภัณฑ์ที่ยังไม่มีรูปจึงค้นเจอจากชื่อได้

รูปที่ผู้ใช้ส่งมา **ไม่ถูกบันทึกที่ไหนเลย** (PDPA) — อยู่ใน RAM ระหว่างคำขอแล้วทิ้ง
vision ล่ม/ไม่ได้ตั้งค่า = 503 ระบบยืมอื่นทำงานปกติ
"""
import asyncio
import hashlib
import math
import os
import statistics

import httpx
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.embedding import Embedding
from app.models.equipment import Equipment
from app.schemas.equipment import ImageSearchResult
from app.services.equipment_service import ALLOWED_IMAGE_EXT, MAX_IMAGE_BYTES, _read_validated

TOP_K = 5
TEXT_BATCH = 32  # vision รับได้สูงสุด 64 ข้อความต่อครั้ง

_fill_lock = asyncio.Lock()
_fill_task: asyncio.Task | None = None  # เก็บ reference ไว้ ไม่งั้น task ถูก GC กลางทาง


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _unavailable() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Image search is temporarily unavailable.")


async def _vision(method: str, path: str, timeout: float = 60, **kw) -> dict:
    """เรียก container vision — ทุกความผิดพลาดของการเชื่อมต่อกลายเป็น 503 จุดเดียว"""
    if not settings.VISION_URL:
        raise _unavailable()
    try:
        async with httpx.AsyncClient(base_url=settings.VISION_URL, timeout=timeout) as c:
            r = await c.request(method, path, **kw)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise _unavailable() from e


def _upload_path(url: str) -> str:
    """/uploads/equipment/x.jpg → ไฟล์จริง (มีโฟลเดอร์ย่อย) · url มาจาก DB ที่เจ้าหน้าที่ส่งได้ จึงกัน ../ หลุดออกนอก UPLOAD_DIR"""
    root = os.path.realpath(settings.UPLOAD_DIR)
    path = os.path.realpath(os.path.join(root, url.removeprefix("/uploads/")))
    return path if path.startswith(root + os.sep) else ""


async def _gallery(db: AsyncSession) -> list[dict]:
    """รุ่นที่ค้นเจอได้ = ยืมได้และไม่ปลดระวาง จับกลุ่มด้วย name+item_type (แบบ find_group_members)

    ข้อความของรุ่น = ชื่อ + รุ่น + ผู้ผลิต + ชื่อตามทะเบียน (ถ้าต่างจากชื่อ) — ชุดเดียวกับ PoC
    """
    rows = (await db.execute(
        select(Equipment).where(Equipment.is_borrowable, Equipment.status != "retired").order_by(Equipment.code)
    )).scalars().all()
    groups: dict[tuple[str, str], list[Equipment]] = {}
    for r in rows:
        groups.setdefault((r.name, r.item_type), []).append(r)
    out = []
    for (name, _), ms in groups.items():
        def distinct(attr: str) -> str:
            return " ".join(sorted({v.strip() for m in ms if (v := getattr(m, attr)) and v.strip()}))
        parts = [name, distinct("model_number"), distinct("manufacturer")]
        asset = distinct("asset_name")
        if asset and asset != name:
            parts.append(asset)
        imgs = sorted({u for m in ms for u in (m.image_urls or []) if (p := _upload_path(u)) and os.path.isfile(p)})
        out.append({
            "rep": ms[0], "members": ms, "text": " ".join(p for p in parts if p), "imgs": imgs,
        })
    return out


def _needed(gallery: list[dict]) -> dict[tuple[str, str], str]:
    """(kind, hash) → แหล่ง (ข้อความ หรือ url รูป) ที่ต้องมีเวกเตอร์"""
    need = {("text", _h(g["text"])): g["text"] for g in gallery}
    need.update({("image", _h(u)): u for g in gallery for u in g["imgs"]})
    return need


async def _load_vectors(db: AsyncSession, model: str, keys: list[tuple[str, str]]) -> dict[tuple[str, str], list[float]]:
    if not keys:
        return {}
    rows = (await db.execute(select(Embedding).where(
        Embedding.model == model, tuple_(Embedding.kind, Embedding.source_hash).in_(keys)))).scalars().all()
    return {(e.kind, e.source_hash): e.vector for e in rows}


async def fill_missing() -> dict:
    """เติมเวกเตอร์ที่ยังขาด + ลบของที่ไม่มีรุ่นไหนอ้างแล้ว — เรียกจาก job ทุกคืน และเบื้องหลังหลังค้นเจอว่าขาด

    รันได้ทีละรอบ (lock) — รอบแรกหลัง deploy ใช้ ~1 วิ/รูป บน VM (~100 รูป ≈ 2 นาที) ระหว่างนั้นค้นได้ แค่บางรุ่นยังไม่มีรูปเทียบ
    """
    if _fill_lock.locked():
        return {"skipped": True}
    async with _fill_lock, AsyncSessionLocal() as db:
        model = (await _vision("GET", "/health", timeout=10))["model"]
        need = _needed(await _gallery(db))
        have = set(await _load_vectors(db, model, list(need)))
        missing = [k for k in need if k not in have]
        texts = [k for k in missing if k[0] == "text"]
        for i in range(0, len(texts), TEXT_BATCH):
            batch = texts[i:i + TEXT_BATCH]
            vecs = (await _vision("POST", "/embed/text", json={"texts": [need[k] for k in batch]}))["vectors"]
            db.add_all(Embedding(kind=k[0], source_hash=k[1], model=model, vector=v) for k, v in zip(batch, vecs))
            await db.commit()
        for k in (k for k in missing if k[0] == "image"):
            with open(_upload_path(need[k]), "rb") as f:
                v = (await _vision("POST", "/embed/image", files={"file": (os.path.basename(need[k]), f.read())}))["vector"]
            db.add(Embedding(kind=k[0], source_hash=k[1], model=model, vector=v))
            await db.commit()  # ทีละรูป — ล่มกลางทางไม่ต้องเริ่มใหม่ทั้งหมด
        # รุ่นที่เปลี่ยนชื่อ/ลบรูป/ปลดระวาง/โมเดลเก่า = แถวกำพร้า
        stale = (await db.execute(select(Embedding.kind, Embedding.source_hash, Embedding.model))).all()
        drop = [(k, h, m) for k, h, m in stale if m != model or (k, h) not in need]
        if drop:
            await db.execute(delete(Embedding).where(
                tuple_(Embedding.kind, Embedding.source_hash, Embedding.model).in_(drop)))
            await db.commit()
        return {"added": len(missing), "removed": len(drop)}


def _kick_fill() -> None:
    """สั่งเติมเบื้องหลังโดยไม่ให้คำขอรอ — แก้ชื่อ/เพิ่มรูปแล้ว การค้นครั้งถัดไปปลุกให้เติมเอง"""
    global _fill_task
    if _fill_lock.locked() or (_fill_task and not _fill_task.done()):
        return

    async def run() -> None:
        try:
            await fill_missing()
        except Exception as e:  # noqa: BLE001 — งานเบื้องหลัง ล้มแล้วรอรอบถัดไป ไม่ให้ทำคำขออื่นพัง
            print(f"[image_search] เติมเวกเตอร์ไม่สำเร็จ: {e!r}")
    _fill_task = asyncio.create_task(run())


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _z(vals: list[float | None]) -> list[float]:
    """z-score เฉพาะค่าที่มี — ไม่มีค่า (รุ่นไม่มีรูป) = -inf ไม่ถูกเลือกจากฝั่งนี้"""
    real = [v for v in vals if v is not None]
    if not real:
        return [-math.inf] * len(vals)
    mu, sd = statistics.fmean(real), statistics.pstdev(real) or 1e-9
    return [-math.inf if v is None else (v - mu) / sd for v in vals]


def combine(img: list[float | None], txt: list[float | None]) -> list[float]:
    """คะแนนรวมต่อรุ่น = max(z รูป, z ชื่อ) — แยกเป็นฟังก์ชันบริสุทธิ์ไว้เทส (วิธีเดียวกับ PoC eval_text.py)"""
    return [max(a, b) for a, b in zip(_z(img), _z(txt))]


async def search_by_image(db: AsyncSession, file: UploadFile) -> list[ImageSearchResult]:
    """รูปถ่าย → 5 รุ่นที่ใกล้ที่สุด · ตรวจไฟล์ด่านเดียวกับทุกการอัปโหลด แต่ไม่เขียนลงดิสก์"""
    contents, ext = await _read_validated(file, ALLOWED_IMAGE_EXT, MAX_IMAGE_BYTES)
    res = await _vision("POST", "/embed/image", files={"file": (f"q{ext}", contents)})
    del contents
    model, q = res["model"], res["vector"]

    gallery = await _gallery(db)
    need = _needed(gallery)
    vecs = await _load_vectors(db, model, list(need))
    if len(vecs) < len(need):
        _kick_fill()

    img_s: list[float | None] = []
    txt_s: list[float | None] = []
    for g in gallery:
        sims = [_dot(q, v) for u in g["imgs"] if (v := vecs.get(("image", _h(u))))]
        img_s.append(max(sims) if sims else None)
        tv = vecs.get(("text", _h(g["text"])))
        txt_s.append(_dot(q, tv) if tv else None)
    scores = combine(img_s, txt_s)

    ranked = sorted((i for i, s in enumerate(scores) if s > -math.inf), key=lambda i: -scores[i])[:TOP_K]
    out = []
    for i in ranked:
        g, rep = gallery[i], gallery[i]["rep"]
        out.append(ImageSearchResult(
            equipment_id=rep.id, name=rep.name, item_type=rep.item_type, unit=rep.unit,
            image_url=next((m.image_url for m in g["members"] if m.image_url), None),
            quantity_total=sum(m.quantity_total for m in g["members"]),
            quantity_available=sum(m.quantity_available for m in g["members"] if m.status == "available"),
            score=round(scores[i], 3),
        ))
    return out


async def health(db: AsyncSession) -> dict:
    """สำหรับการ์ดหน้าตรวจสอบระบบ — vision ตอบไหม + เวกเตอร์ขาดกี่ชิ้น (ไม่ยก exception)"""
    try:
        model = (await _vision("GET", "/health", timeout=5))["model"]
    except HTTPException:
        return {"up": False, "configured": bool(settings.VISION_URL)}
    need = _needed(await _gallery(db))
    have = await _load_vectors(db, model, list(need))
    return {"up": True, "configured": True, "model": model, "total": len(need), "missing": len(need) - len(have)}
