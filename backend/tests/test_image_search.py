"""ค้นหาอุปกรณ์ด้วยรูป (25 พ.ย. 69) — ไม่แตะ DB/vision จริง (mock ทั้งคู่)"""
import io
import math
import os
import types
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from app.core.config import settings
from app.services import image_search_service as s
from app.services.system_check_service import _image_search_check


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "JPEG")
    return buf.getvalue()


def test_combine_text_rescues_group_without_photo():
    # รุ่น 0 มีรูปแต่ไม่ตรง · รุ่น 1 ไม่มีรูป แต่ชื่อตรงมาก → ต้องชนะ
    scores = s.combine([0.2, None, 0.1], [0.1, 0.9, 0.1])
    assert max(range(3), key=lambda i: scores[i]) == 1
    assert s.combine([None, None], [None, None]) == [-math.inf, -math.inf]


def test_upload_path_blocks_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    assert s._upload_path("/uploads/equipment/a.jpg") == str(tmp_path / "equipment" / "a.jpg")
    assert s._upload_path("/uploads/../../etc/passwd") == ""


def test_image_search_card_states():
    assert _image_search_check({"configured": False, "up": False})["status"] == "warn"
    assert _image_search_check({"configured": True, "up": False})["status"] == "error"
    assert _image_search_check({"configured": True, "up": True, "total": 10, "missing": 3})["status"] == "warn"
    assert _image_search_check({"configured": True, "up": True, "total": 10, "missing": 0})["status"] == "ok"


async def test_search_unconfigured_is_503(monkeypatch):
    monkeypatch.setattr(settings, "VISION_URL", "")
    with pytest.raises(HTTPException) as e:
        await s.search_by_image(None, UploadFile(io.BytesIO(_jpeg()), filename="q.jpg"))
    assert e.value.status_code == 503


async def test_search_ranks_and_stores_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    q = [1.0, 0.0]

    async def vision(method, path, **kw):
        return {"model": "m", "vector": q}

    def unit(name, avail, status="available"):
        return types.SimpleNamespace(id=uuid.uuid4(), name=name, item_type="material", unit="ชิ้น", image_url=None,
                                     quantity_total=2, quantity_available=avail, status=status)
    gallery = [{"rep": unit(n, 1), "members": [unit(n, 1), unit(n, 1, "maintenance")], "text": n, "imgs": []}
               for n in ("A", "B", "C", "D", "E", "F")]
    vecs = {("text", s._h(n)): v for n, v in
            zip("ABCDEF", ([0.1, 1], [0.9, 0.1], [0.5, 0.5], [0, 1], [0.2, 1], [0.3, 1]))}

    async def fake_gallery(db):
        return gallery

    async def fake_vectors(db, model, keys):
        return vecs
    monkeypatch.setattr(s, "_vision", vision)
    monkeypatch.setattr(s, "_gallery", fake_gallery)
    monkeypatch.setattr(s, "_load_vectors", fake_vectors)

    res = await s.search_by_image(None, UploadFile(io.BytesIO(_jpeg()), filename="q.jpg"))
    assert [r.name for r in res][:2] == ["B", "C"] and len(res) == s.TOP_K
    assert res[0].quantity_available == 1 and res[0].quantity_total == 4  # หน่วยซ่อมอยู่ไม่นับว่าพร้อมยืม
    assert os.listdir(tmp_path) == []  # รูปของผู้ใช้ไม่ถูกเขียนลงดิสก์
