-- ===========================================
-- แก้เลขครุภัณฑ์ให้ตรงทะเบียน: แทน durable ที่จับคู่ทะเบียนได้ ด้วย 704 ตัวเลขจริง
-- เก็บ: วัสดุ 509 (Snipe code เดิม) + durable พักไว้ 34 (สว่าน/Cisco/AppleTV/webcam/จอ27/AP)
-- ต้องรันคู่กับ seed_equipment.sql (ต่อท้ายในทรานแซกชันเดียว)
-- ===========================================

-- 1) ลบข้อมูลยืมทดสอบ (อ้างถึงครุภัณฑ์เก่า, FK NO ACTION)
DELETE FROM notifications WHERE borrow_request_id IS NOT NULL;
DELETE FROM borrow_items;
DELETE FROM borrow_requests;

-- 2) ลบ durable ที่จับคู่ทะเบียนได้ (เลข Snipe ผิด) — เก็บเฉพาะ 8 กลุ่มพักไว้
DELETE FROM equipment
WHERE item_type = 'durable'
  AND name NOT IN (
    'AC1200 Wireless Access Point',
    'ครุภัณฑ์จอแสดงภาพ ขนาด 27 นิ้ว',
    'WEBCAM ARROW X 1080HD',
    'OKER Full HD Webcam',
    'Apple TV HD',
    'สว่านกระแทกไร้สาย 12V 47.5 Nm. Brushless DEWALT',
    'WS-C2960-24TC-L',
    'Router-ISR-4321'
  );
-- equipment_category_links ลบเองผ่าน ON DELETE CASCADE
