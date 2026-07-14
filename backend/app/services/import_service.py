"""นำเข้า/อัปเดตอุปกรณ์จากไฟล์ทะเบียนคุมทรัพย์สิน (Excel)

ไหลงาน 2 ขั้น เพื่อให้แอดมินตรวจก่อนของเข้าจริง:
  1. preview — อัปโหลดไฟล์ เก็บไว้ใน uploads/imports/ แล้วอ่านเทียบกับ DB คืน "ร่าง"
     ว่าจะเพิ่มอะไร แก้อะไร ชำรุด/สูญหายอะไร และอะไรหายไปจากทะเบียน (เสนอปลดระวาง)
  2. commit — อ่านไฟล์เดิมซ้ำจาก import_id แล้ว apply จริง + เขียน audit log
     (อ่านไฟล์ซ้ำแทนที่จะเชื่อ diff ที่ client ส่งกลับมา — client แก้ payload ไม่ได้)

audit log ที่เขียนตอน commit ใช้ action เดียวกับการเพิ่ม/ปลดระวางด้วยมือ
จึงออกใบรับเข้าคลัง/ใบปลดระวาง (GET /equipment/stock-document) ได้ทันทีหลังนำเข้า
"""
import os
import uuid
from typing import Any

import openpyxl
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.equipment import Equipment
from app.models.equipment_category import EquipmentCategory
from app.models.user import User
from app.schemas.equipment import ImportCommitRequest
from app.services import audit_service, ocr_import

# กฎจัดหมวดตามคีย์เวิร์ด — ชุดเดียวกับ scripts/import_register.py ที่ใช้ seed ครั้งแรก
# เช็คจากบนลงล่าง เจอก่อนชนะ (คอมพิวเตอร์มาก่อนเฟอร์นิเจอร์ ไม่งั้น "คอมพิวเตอร์ตั้งโต๊ะ" เข้าหมวดโต๊ะ)
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("คอมพิวเตอร์", ["คอมพิวเตอร์", "optiplex", "acer", "โน๊ตบุ๊ค", "โน้ตบุ๊ค",
                     "thinkpad", "แม่ข่าย", "micro pc", "กราฟฟิก", "หน้าจอ", "จอแสดงผล"]),
    ("ซอฟต์แวร์/ลิขสิทธิ์", ["ซอฟต์แวร์", "ลิขสิทธิ์", "ชุดโปรแกรม"]),
    ("โสตทัศนูปกรณ์", ["โทรทัศน์", "led tv", "smart tv"]),
    ("อุปกรณ์อิเล็กทรอนิกส์/เครื่องมือวัด",
     ["มัลติมิเตอร์", "oscilloscope", "เครื่องวัด", "เครื่องกำเนิด", "แหล่งจ่าย",
      "เครื่องทดสอบ", "ลอจิก", "iot", "ไอโอที", "sensor", "แผงวงจร", "สมองกล",
      "virtual reality", "คลัสเตอร์", "big data", "ไฟฟ้า", "เครื่องมือวัด",
      "อิเล็กทรอนิกส์", "ทดลอง", "ทดสอบ", "อุปกรณ์วัด"]),
    ("โต๊ะ/ตู้/เฟอร์นิเจอร์", ["โต๊ะ", "โตะ", "เก้าอี้", "ตู้", "ชั้นวาง"]),
]
FALLBACK_CAT = "ไม่ระบุหมวดหมู่"

# รหัสวัสดุ 2 หลักแรก = หมวดวัสดุ (ครุภัณฑ์ไม่ใช้ — 2 หลักแรกของครุภัณฑ์คือปีงบประมาณ 63-67)
MATERIAL_CAT_BY_PREFIX: dict[str, str] = {
    "10": "อุปกรณ์ใช้งานทั่วไป",
    "12": "อุปกรณ์คอมพิวเตอร์/ต่อพ่วง",   # webcam
    "13": "อุปกรณ์คอมพิวเตอร์/ต่อพ่วง",   # converter, hub, card reader
    "21": "บอร์ด/ไมโครคอนโทรลเลอร์",
    "22": "บอร์ด/ไมโครคอนโทรลเลอร์",
    "23": "บอร์ด/ไมโครคอนโทรลเลอร์",
    "30": "เครื่องมือช่าง",
    "33": "ชุดการเรียนรู้",
    "34": "อุปกรณ์อิเล็กทรอนิกส์/เครื่องมือวัด",
    "35": "อุปกรณ์อิเล็กทรอนิกส์/เครื่องมือวัด",
    "36": "อุปกรณ์อิเล็กทรอนิกส์/เครื่องมือวัด",
    "61": "อุปกรณ์เครือข่าย",
}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# ประเภทในคอลัมน์ "ประเภท" ของชีตวัสดุ → item_type ในระบบ (ไม่ตรงคำไหน = วัสดุใช้ซ้ำ)
_MATERIAL_TYPES = {
    "วัสดุใช้ซ้ำ": "material", "material": "material",
    "วัสดุสิ้นเปลือง": "consumable", "consumable": "consumable",
}


def _clean(v: object) -> str:
    """ตัด whitespace/ขึ้นบรรทัดที่ติดมาจากเซลล์ Excel"""
    return " ".join(str(v).split()) if v is not None else ""


def _categorize(name: str, code: str = "", item_type: str = "durable") -> str:
    """หมวดหมู่ของรายการ — วัสดุใช้รหัส 2 หลักแรก (หมวดวัสดุ) ก่อน ไม่เจอค่อยเดาจากชื่อ"""
    if item_type != "durable" and code[:2] in MATERIAL_CAT_BY_PREFIX:
        return MATERIAL_CAT_BY_PREFIX[code[:2]]
    low = name.lower()
    for cat, keys in CATEGORY_RULES:
        if any(k in low for k in keys):
            return cat
    return FALLBACK_CAT


def _status_from(normal: object, broken: object, worn: object, lost: object) -> tuple[str, int]:
    """แปลงคอลัมน์ ปกติ/ชำรุด/เสื่อมสภาพ/สูญหาย ในทะเบียน → (status, quantity_available)"""
    if broken:
        return "damaged", 0
    if lost or worn:
        return "unavailable", 0
    return "available", 1


def parse_workbook(path: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """อ่านไฟล์ทะเบียน คืน (รายการที่มีเลขครุภัณฑ์, รายการที่ไม่มีเลข — ข้ามไป)

    รองรับ 2 ชีตของทะเบียนคณะ: ชีตคณะ (เลขปกติ) และชีตพระราชทาน (ใช้ "รหัสครุภัณฑ์ใหม่")
    """
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="อ่านไฟล์ Excel ไม่สำเร็จ")

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    def add(code: str, name: str, loc: str, st: str, qa: int, sheet: str, seq: str,
            item_type: str = "durable", qty: int = 1, unit: str | None = None) -> None:
        if not code or code == "-":
            skipped.append({"sheet": sheet, "seq": seq, "name": name, "reason": "ไม่มีเลขครุภัณฑ์/รหัส"})
            return
        rows.append({
            "code": code, "name": name, "location": loc or None,
            "status": st, "quantity_available": qa, "category": _categorize(name, code, item_type),
            "item_type": item_type, "quantity_total": qty, "unit": unit,
        })

    if "คณะเทคโนฯดิจิทัล" in wb.sheetnames:
        for r in wb["คณะเทคโนฯดิจิทัล"].iter_rows(min_row=5, values_only=True):
            name = _clean(r[2])
            if not name or name == "รวมทั้งสิ้น":
                continue
            st, qa = _status_from(r[5], r[6], r[7], r[8])
            add(_clean(r[1]), name, _clean(r[11]) or _clean(r[16]), st, qa, "คณะ", _clean(r[0]))

    if "ครุภัณฑ์ที่ได้รับพระราชทาน" in wb.sheetnames:
        for r in wb["ครุภัณฑ์ที่ได้รับพระราชทาน"].iter_rows(min_row=5, values_only=True):
            name = _clean(r[1])
            if not name or name == "รวมทั้งสิ้น":
                continue
            st, qa = _status_from(r[10], r[11], r[12], r[13])
            # "ไม่พบครุภัณฑ์" ในหมายเหตุ = หาตัวจริงไม่เจอ → ยืมไม่ได้
            if "ไม่พบครุภัณฑ์" in _clean(r[15]):
                st, qa = "unavailable", 0
            add(_clean(r[8]), name, _clean(r[9]), st, qa, "พระราชทาน", _clean(r[0]))

    # ชีต "วัสดุ" (ทางเลือก) — วัสดุไม่มีในทะเบียนคุมทรัพย์สิน จึงใช้ชีตแยกรูปแบบง่าย ๆ
    # header แถว 1: รหัส | รายการ | ประเภท | หน่วยนับ | จำนวน | สถานที่จัดเก็บ
    if "วัสดุ" in wb.sheetnames:
        for i, r in enumerate(wb["วัสดุ"].iter_rows(min_row=2, values_only=True), 2):
            name = _clean(r[1]) if len(r) > 1 else ""
            if not name:
                continue
            item_type = _MATERIAL_TYPES.get(_clean(r[2]), "material")
            qty = int(r[4] or 0) if len(r) > 4 else 0
            add(_clean(r[0]), name, _clean(r[5]) if len(r) > 5 else "",
                "available" if qty > 0 else "unavailable", qty, "วัสดุ", str(i),
                item_type=item_type, qty=qty, unit=_clean(r[3]) or None)

    wb.close()
    if not rows and not skipped:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ไม่พบข้อมูลในไฟล์ — ต้องมีชีต 'คณะเทคโนฯดิจิทัล' หรือ 'ครุภัณฑ์ที่ได้รับพระราชทาน'",
        )
    return rows, skipped


STATUS_LABEL = {"available": "ปกติ", "damaged": "ชำรุด", "unavailable": "สูญหาย/เสื่อมสภาพ",
                "retired": "ปลดระวาง", "under_repair": "ซ่อม", "borrowed": "ถูกยืม"}


def diff_rows(rows: list[dict[str, Any]], existing: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """เทียบรายการในไฟล์กับของใน DB → คืนร่างการเปลี่ยนแปลงทีละรายการ

    action:
      new       = ยังไม่มีใน DB → จะเพิ่มเข้าคลัง
      update    = มีอยู่แล้วแต่ชื่อ/สถานที่/สถานะไม่ตรง → จะแก้ตามไฟล์
      unchanged = ตรงกันทุกอย่าง → ไม่ทำอะไร
      retire    = มีใน DB (ครุภัณฑ์) แต่หายไปจากไฟล์ทะเบียน → เสนอปลดระวาง (ต้องติ๊กยืนยันแยก)
    """
    result: list[dict[str, Any]] = []
    for row in rows:
        old = existing.get(row["code"])
        if old is None:
            result.append({"action": "new", **row, "changes": {}})
            continue
        changes: dict[str, list[Any]] = {}
        for field in ("name", "location", "status"):
            if (old.get(field) or None) != (row.get(field) or None):
                changes[field] = [old.get(field), row.get(field)]
        # จำนวนเทียบเฉพาะวัสดุ — ครุภัณฑ์เป็น 1 ชิ้น/1 เลขทะเบียนเสมอ
        if row["item_type"] != "durable" and old.get("quantity_total") != row["quantity_total"]:
            changes["quantity_total"] = [old.get("quantity_total"), row["quantity_total"]]
        result.append({
            "action": "update" if changes else "unchanged", **row,
            "item_type": old["item_type"],  # ประเภทของเดิมใน DB ชนะ (แอดมินอาจจัดประเภทไว้แล้ว)
            "changes": changes,
        })

    in_file = {row["code"] for row in rows}
    for code, old in existing.items():
        # เฉพาะครุภัณฑ์ที่ยังไม่ปลดระวาง — วัสดุ (material/consumable) ไม่ได้อยู่ในทะเบียนอยู่แล้ว
        if code not in in_file and old["item_type"] == "durable" and old["status"] != "retired":
            result.append({
                "action": "retire", "code": code, "name": old["name"],
                "location": old.get("location"), "status": "retired",
                "quantity_available": 0, "category": None, "item_type": old["item_type"],
                "quantity_total": old.get("quantity_total", 1), "unit": None, "changes": {},
            })
    return result


async def _load_existing(db: AsyncSession) -> dict[str, dict[str, Any]]:
    result = await db.execute(select(Equipment))
    return {
        eq.code: {"id": eq.id, "name": eq.name, "location": eq.location, "status": eq.status,
                  "item_type": eq.item_type, "quantity_total": eq.quantity_total}
        for eq in result.scalars().all()
    }


def _summarize(diff: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"new": 0, "update": 0, "unchanged": 0, "retire": 0}
    for d in diff:
        counts[d["action"]] += 1
    return counts


def _parse_file(path: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Excel → อ่านตามชีตทะเบียน / รูป-PDF → OCR (โหมดทดลอง) — คืน rows รูปแบบเดียวกัน"""
    if ocr_import.is_scan(path):
        return ocr_import.parse_scan(path)
    return parse_workbook(path)


def _import_path(import_id: str) -> str | None:
    """หาไฟล์ที่อัปโหลดไว้จาก import_id (นามสกุลต่างกันได้ตามชนิดไฟล์ที่แอดมินอัปมา)"""
    import_dir = os.path.join(settings.UPLOAD_DIR, "imports")
    for ext in (".xlsx", *ocr_import.SCAN_EXTS):
        path = os.path.join(import_dir, f"{import_id}{ext}")
        if os.path.exists(path):
            return path
    return None


async def preview_import(db: AsyncSession, file: UploadFile) -> dict[str, Any]:
    """รับไฟล์ทะเบียน (Excel หรือรูป/PDF) เก็บไว้ แล้วคืนร่างว่าจะเปลี่ยนอะไรบ้าง (ยังไม่แตะ DB)"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext != ".xlsx" and not ocr_import.is_scan(file.filename or ""):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="รองรับไฟล์ .xlsx หรือรูปถ่าย/PDF ของทะเบียน (.jpg .png .pdf)")
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ไฟล์ใหญ่เกิน 10MB")

    import_dir = os.path.join(settings.UPLOAD_DIR, "imports")
    os.makedirs(import_dir, exist_ok=True)
    import_id = uuid.uuid4().hex
    path = os.path.join(import_dir, f"{import_id}{ext}")
    with open(path, "wb") as f:
        f.write(contents)

    rows, skipped = _parse_file(path)
    diff = diff_rows(rows, await _load_existing(db))
    return {
        "import_id": import_id,
        "filename": file.filename,
        "summary": _summarize(diff),
        "rows": diff,
        "skipped": skipped,
    }


async def _get_or_create_category(db: AsyncSession, name: str, cache: dict[str, EquipmentCategory]) -> EquipmentCategory:
    if name in cache:
        return cache[name]
    cat = (await db.execute(
        select(EquipmentCategory).where(EquipmentCategory.name == name)
    )).scalar_one_or_none()
    if cat is None:
        cat = EquipmentCategory(name=name)
        db.add(cat)
        await db.flush()
    cache[name] = cat
    return cat


async def commit_import(
    db: AsyncSession, admin: User, import_id: str, body: ImportCommitRequest
) -> dict[str, int]:
    """บันทึกร่างที่แอดมินตรวจ/แก้แล้วเข้าระบบจริง — เพิ่ม / แก้ / ปลดระวาง ตามบรรทัดที่ส่งมา

    บรรทัดที่แอดมินตัดออกจากร่าง จะไม่ถูกบันทึก และไฟล์ต้นทางถูกอ่านซ้ำเพื่อยืนยันว่า
    ทุกบรรทัดที่ส่งมามีอยู่ในไฟล์จริงและ action ตรงกับที่ระบบคำนวณไว้ (กันร่างถูกยัดของแปลกปลอม)
    แต่ค่า ชื่อ/สถานที่/สถานะ ใช้ตามที่แอดมินแก้ในร่าง

    เขียน audit log ทุกบรรทัด ทำให้ออกใบรับเข้าคลัง/ใบปลดระวางตามช่วงวันที่ได้ทันทีหลังบันทึก
    """
    if not import_id.isalnum():  # กัน path traversal จาก import_id ที่ปลอมมา
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="import_id ไม่ถูกต้อง")
    path = _import_path(import_id)
    if not path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบไฟล์นำเข้า กรุณาอัปโหลดใหม่")

    rows, _ = _parse_file(path)
    existing = await _load_existing(db)
    allowed = {d["code"]: d for d in diff_rows(rows, existing)}

    applied = {"new": 0, "update": 0, "retire": 0}
    cat_cache: dict[str, EquipmentCategory] = {}
    src = body.filename or os.path.basename(path)

    for row in body.rows:
        ref = allowed.get(row.code)
        if ref is None or ref["action"] != row.action or row.action == "unchanged":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"รายการ {row.code} ไม่ตรงกับไฟล์ที่อัปโหลด กรุณาอ่านไฟล์ใหม่",
            )

        cat_names = row.categories or [ref.get("category") or FALLBACK_CAT]

        if row.action == "new":
            eq = Equipment(
                code=row.code, name=row.name, item_type=row.item_type,
                location=row.location, status=row.status,
                unit=row.unit, description=row.description,
                quantity_total=row.quantity,
                quantity_available=row.quantity if row.status == "available" else 0,
                image_urls=row.image_urls, image_url=row.image_urls[0] if row.image_urls else None,
            )
            eq.categories = [await _get_or_create_category(db, n, cat_cache) for n in cat_names]
            db.add(eq)
            await db.flush()
            await audit_service.log_action(
                db, admin, "create_equipment", "equipment", eq.id,
                {"code": eq.code, "name": eq.name, "quantity": eq.quantity_total,
                 "item_type": eq.item_type, "source": src},
            )
            applied["new"] += 1
            continue

        eq = (await db.execute(
            select(Equipment).where(Equipment.id == existing[row.code]["id"]).options(selectinload(Equipment.categories))
        )).scalar_one()

        if row.action == "retire":
            eq.status = "retired"
            eq.quantity_available = 0
            await audit_service.log_action(
                db, admin, "retire_equipment", "equipment", eq.id,
                {"code": eq.code, "name": eq.name, "quantity": eq.quantity_total,
                 "item_type": eq.item_type,
                 "reason": (row.reason or "").strip() or f"ไม่พบในทะเบียนฉบับ {src}"},
            )
            applied["retire"] += 1
            continue

        # action == update — เขียนทับด้วยค่าที่แอดมินยืนยันในร่าง
        old_status, old_qty = eq.status, eq.quantity_total
        eq.name, eq.location, eq.status = row.name, row.location, row.status
        eq.item_type, eq.quantity_total = row.item_type, row.quantity
        if row.unit is not None:
            eq.unit = row.unit
        if row.description is not None:
            eq.description = row.description
        if row.image_urls:
            eq.image_urls = row.image_urls
            eq.image_url = row.image_urls[0]
        if row.categories:
            eq.categories = [await _get_or_create_category(db, n, cat_cache) for n in row.categories]
        # แตะ quantity_available เฉพาะตอนสถานะ/จำนวนรวมเปลี่ยน — ของที่ถูกยืมอยู่จะได้ไม่โดนรีเซ็ต
        if row.status != old_status or row.quantity != old_qty:
            eq.quantity_available = row.quantity if row.status == "available" else 0
        await audit_service.log_action(
            db, admin, "update_equipment", "equipment", eq.id,
            {"code": eq.code, "fields": sorted(ref["changes"].keys()), "source": src},
        )
        applied["update"] += 1

    await db.commit()
    return applied
