"""
Migrate equipment data from Snipe-IT (MySQL) → our system (PostgreSQL).

Usage (run on Snipe-IT server):
    pip install pymysql
    python import_equipment.py > seed_equipment.sql

Then copy to this machine and run:
    psql $DATABASE_URL -f seed_equipment.sql
"""
import os
import sys
import pymysql
import uuid

MYSQL = dict(
    host=os.environ.get("SNIPEIT_DB_HOST", "127.0.0.1"),
    user=os.environ.get("SNIPEIT_DB_USER", "snipeit"),
    password=os.environ["SNIPEIT_DB_PASSWORD"],  # บังคับใส่ — ไม่มี default
    database=os.environ.get("SNIPEIT_DB_NAME", "snipeit"),
    charset="utf8mb4",
)

# Snipe-IT status_id → our equipment.status
# status 5+ with "อยู่ระหว่างการยืม" = was available before checkout,
# import as available (our system tracks borrow state via borrow_requests)
STATUS_MAP: dict[int, str] = {
    1: "unavailable",  # Pending
    2: "available",    # Ready to Deploy
    3: "unavailable",  # Archived
    4: "available",    # Deployabled
    5: "available",    # อยู่ระหว่างการยืม
    6: "unavailable",  # ตรวจสอบ
    7: "unavailable",  # ไม่ให้ยืม
    8: "damaged",      # ชำรุด
    10: "unavailable", # Lost - สูญหาย
}

def map_status(status_id: int, status_name: str) -> str:
    if status_id in STATUS_MAP:
        return STATUS_MAP[status_id]
    # bug statuses (id 9, 11-36): infer from name prefix
    name = status_name or ""
    if "อยู่ระหว่างการยืม" in name:
        return "available"
    if "Ready to Deploy" in name:
        return "available"
    return "unavailable"

def q(s: object) -> str:
    """Quote a value for SQL."""
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def main() -> None:
    conn = pymysql.connect(**MYSQL)
    cur = conn.cursor(pymysql.cursors.DictCursor)

    # --- categories (asset type only, deduplicate by name) ---
    cur.execute("""
        SELECT DISTINCT TRIM(name) as name
        FROM categories
        WHERE category_type = 'asset' AND deleted_at IS NULL AND name IS NOT NULL
        ORDER BY name
    """)
    raw_cats = [r["name"] for r in cur.fetchall()]
    # assign stable UUIDs so equipment FK can reference them
    cat_uuids: dict[str, str] = {name: str(uuid.uuid4()) for name in raw_cats}

    print("-- ===========================================")
    print("-- Snipe-IT → Equipment Borrowing System seed")
    print("-- ===========================================")
    print("BEGIN;")
    print()
    print("-- Categories")
    for name, uid in cat_uuids.items():
        print(
            f"INSERT INTO equipment_categories (id, name) "
            f"VALUES ({q(uid)}, {q(name)}) "
            f"ON CONFLICT (name) DO NOTHING;"
        )

    # fallback category for assets whose model has no asset-type category
    fallback_name = "ไม่ระบุหมวดหมู่"
    fallback_uid = str(uuid.uuid4())
    cat_uuids[fallback_name] = fallback_uid
    print(
        f"INSERT INTO equipment_categories (id, name) "
        f"VALUES ({q(fallback_uid)}, {q(fallback_name)}) "
        f"ON CONFLICT (name) DO NOTHING;"
    )

    # --- assets ---
    cur.execute("""
        SELECT
            a.id,
            a.name,
            a.asset_tag,
            a.notes,
            a._snipeit_lekh_khrphnth_7 AS asset_number,
            a.status_id,
            s.name AS status_name,
            c.name AS category_name,
            c.category_type,
            l.name AS location_name
        FROM assets a
        LEFT JOIN models m ON a.model_id = m.id
        LEFT JOIN categories c ON m.category_id = c.id
        LEFT JOIN status_labels s ON a.status_id = s.id
        LEFT JOIN locations l ON a.rtd_location_id = l.id
        WHERE a.deleted_at IS NULL
        ORDER BY a.asset_tag
    """)
    assets = cur.fetchall()

    print()
    print(f"-- Equipment ({len(assets)} records)")
    skipped = 0
    for a in assets:
        code = (a["asset_tag"] or "").strip()
        if not code:
            skipped += 1
            continue

        name = (a["name"] or code).strip()
        status = map_status(a["status_id"] or 0, a["status_name"] or "")

        # category: use asset-type category or fallback
        cat_name = (a["category_name"] or "").strip()
        if a.get("category_type") != "asset" or cat_name not in cat_uuids:
            cat_name = fallback_name
        cat_uid = cat_uuids[cat_name]

        qty_available = 1 if status == "available" else 0
        notes = a["notes"]
        location = a["location_name"]
        uid = str(uuid.uuid4())

        print(
            f"INSERT INTO equipment "
            f"(id, code, name, category_id, item_type, status, "
            f"quantity_total, quantity_available, description, location) VALUES ("
            f"{q(uid)}, {q(code)}, {q(name)}, {q(cat_uid)}, 'durable', {q(status)}, "
            f"1, {qty_available}, {q(notes)}, {q(location)}"
            f") ON CONFLICT (code) DO NOTHING;"
        )

    print()
    print("COMMIT;")

    conn.close()

    if skipped:
        print(f"-- WARNING: skipped {skipped} assets with no asset_tag", file=sys.stderr)
    print(f"-- Done: {len(assets) - skipped} equipment, {len(cat_uuids)} categories", file=sys.stderr)


if __name__ == "__main__":
    main()
