-- ===========================================
-- แยกประเภทที่ 3 "material" (วัสดุใช้ซ้ำ) ออกจาก consumable (วัสดุสิ้นเปลือง)
-- + ย้าย hold 34 -> material/ไม่ระบุหมวดหมู่ + รวมหมวดอังกฤษ->ไทย
-- ===========================================
BEGIN;

-- 1) consumable ที่ไม่ใช่สิ้นเปลืองจริง (บอร์ด/คิต/สาย/เครื่องมือ) -> material
UPDATE equipment SET item_type = 'material'
WHERE item_type = 'consumable'
  AND name NOT IN ('ตะกั่ว', 'Soldering paste', 'สายไฟ');

-- 2) ของพักไว้ 34 -> material
UPDATE equipment SET item_type = 'material'
WHERE name IN (
  'AC1200 Wireless Access Point','ครุภัณฑ์จอแสดงภาพ ขนาด 27 นิ้ว','WEBCAM ARROW X 1080HD',
  'OKER Full HD Webcam','Apple TV HD','สว่านกระแทกไร้สาย 12V 47.5 Nm. Brushless DEWALT',
  'WS-C2960-24TC-L','Router-ISR-4321');

-- ย้าย hold ไปหมวด "ไม่ระบุหมวดหมู่" (ลบ link เดิมทั้งหมด ใส่ใหม่)
DELETE FROM equipment_category_links WHERE equipment_id IN (
  SELECT id FROM equipment WHERE name IN (
  'AC1200 Wireless Access Point','ครุภัณฑ์จอแสดงภาพ ขนาด 27 นิ้ว','WEBCAM ARROW X 1080HD',
  'OKER Full HD Webcam','Apple TV HD','สว่านกระแทกไร้สาย 12V 47.5 Nm. Brushless DEWALT',
  'WS-C2960-24TC-L','Router-ISR-4321'));
INSERT INTO equipment_category_links (equipment_id, category_id)
SELECT e.id, (SELECT id FROM equipment_categories WHERE name='ไม่ระบุหมวดหมู่')
FROM equipment e WHERE e.name IN (
  'AC1200 Wireless Access Point','ครุภัณฑ์จอแสดงภาพ ขนาด 27 นิ้ว','WEBCAM ARROW X 1080HD',
  'OKER Full HD Webcam','Apple TV HD','สว่านกระแทกไร้สาย 12V 47.5 Nm. Brushless DEWALT',
  'WS-C2960-24TC-L','Router-ISR-4321')
ON CONFLICT DO NOTHING;

-- 3) รวมหมวดภาษาอังกฤษ -> หมวดไทยตัวเดียวกัน (re-point links แล้วลบหมวดว่าง)
-- Computer -> คอมพิวเตอร์
INSERT INTO equipment_category_links (equipment_id, category_id)
SELECT l.equipment_id, (SELECT id FROM equipment_categories WHERE name='คอมพิวเตอร์')
FROM equipment_category_links l WHERE l.category_id=(SELECT id FROM equipment_categories WHERE name='Computer')
ON CONFLICT DO NOTHING;
-- Electronic + Embedded -> อุปกรณ์อิเล็กทรอนิกส์/เครื่องมือวัด
INSERT INTO equipment_category_links (equipment_id, category_id)
SELECT l.equipment_id, (SELECT id FROM equipment_categories WHERE name='อุปกรณ์อิเล็กทรอนิกส์/เครื่องมือวัด')
FROM equipment_category_links l WHERE l.category_id IN (SELECT id FROM equipment_categories WHERE name IN ('Electronic','Embedded'))
ON CONFLICT DO NOTHING;

-- ลบหมวดอังกฤษ (links cascade + hold/merge ทำให้ว่างแล้ว) + โตะตู้ ที่สะกดซ้ำ
DELETE FROM equipment_categories WHERE name IN ('Computer','Electronic','Embedded','Network','Tools','TV','โตะตู้');

COMMIT;
