// ป้ายภาษาไทยของ audit log — ใช้ร่วมกันระหว่างหน้า Audit Log รวม และไทม์ไลน์ประวัติรายอุปกรณ์
// (เดิมนิยามอยู่ในหน้า AuditLogPage ที่เดียว ทำให้ไทม์ไลน์ที่อื่นต้องคัดลอกไปซ้ำ)
import { formatDate, formatDateTime } from '../../utils/formatDate.js'

export const ACTION_LABEL = {
  // ฝั่งผู้ยืม (บันทึกตั้งแต่ 5 ก.ย. 69) — เดิม log มีแต่ฝั่งแอดมิน เลยตอบไม่ได้ว่าเรื่องเริ่มจากใคร
  create_request: 'ยื่นคำขอยืม',
  cancel_request: 'ยกเลิกคำขอ',
  request_return: 'แจ้งขอคืน',
  request_renew: 'ขอต่อเวลา',
  upload_signed_form: 'อัปโหลดใบยืมที่เซ็นแล้ว',
  view_signed_form: 'เปิดดูใบยืมที่เซ็นแล้ว',
  handover_request: 'จ่ายของ + เซ็นรับบนหน้าจอ',
  sign_return: 'เซ็นรับคืนบนหน้าจอ',
  view_signature: 'เปิดดูลายเซ็น',
  register: 'สมัครใช้งาน',
  import_eligible_students: 'นำเข้ารายชื่อนักศึกษาที่รับรอง',
  delete_eligible_student: 'ถอนรายชื่อนักศึกษาที่รับรอง',
  approve_registration: 'อนุมัติผู้สมัคร',
  reject_registration: 'ปฏิเสธผู้สมัคร',
  verify_email: 'ยืนยันอีเมล',
  // จัดการผู้ใช้ / ค่าระบบ
  create_user: 'สร้างบัญชีผู้ใช้',
  update_user_status: 'เปิด/ปิดใช้งานบัญชี',
  delete_user: 'ลบบัญชีผู้ใช้',
  update_setting: 'แก้ไขการตั้งค่าระบบ',
  update_user_role: 'เปลี่ยนระดับสิทธิ์',
  create_change_request: 'ยื่นคำขอแก้ไขข้อมูล',
  decide_change_request: 'ตัดสินคำขอแก้ไขข้อมูล',
  delete_request: 'ลบประวัติการยืม',
  approve_request: 'อนุมัติคำขอ',
  reject_request: 'ปฏิเสธคำขอ',
  approve_renew: 'อนุมัติต่อเวลา',
  reject_renew: 'ปฏิเสธต่อเวลา',
  confirm_return: 'รับคืนอุปกรณ์',
  // ค่าปรับ (เฟส 6) — ทุกการแตะตัวเลขที่เรียกเงินต้องอ่านออกว่าใครทำอะไรเพราะอะไร
  update_fine: 'แก้ยอดค่าปรับ',
  pay_fine: 'บันทึกชำระค่าปรับ',
  waive_fine: 'ยกเว้นค่าปรับ',
  create_equipment: 'เพิ่มอุปกรณ์',
  update_equipment: 'แก้ไขอุปกรณ์',
  retire_equipment: 'ปลดระวางอุปกรณ์',
  delete_equipment: 'ลบอุปกรณ์',
  split_equipment: 'แยกอุปกรณ์เป็นรายชิ้น',
  restock_equipment: 'เติมของเข้าคลัง',
  adjust_stock: 'ปรับยอดคงเหลือ',
  bulk_update_equipment: 'แก้ไขหลายรายการ',
  bulk_adjust_stock: 'ปรับยอดคงเหลือ (หลายรายการ)',
  create_bundle: 'สร้างชุดอุปกรณ์',
  update_bundle: 'แก้ไขชุดอุปกรณ์',
  delete_bundle: 'ลบชุดอุปกรณ์',
  physical_audit: 'ตรวจนับอุปกรณ์',
  install_part: 'ติดตั้งชิ้นส่วน',
  update_part: 'แก้ไขชิ้นส่วน',
  remove_part: 'ถอดชิ้นส่วน',
  // ค่าคุณภาพ + ชั้นปี (เฟส 10, 15 ก.ย. 69)
  assess_quality: 'ประเมินคุณภาพ',
  update_user_study: 'แก้ไขข้อมูลชั้นปี',
}

// ชื่อฟิลด์ในภาษาคน — ที่ผ่านมา modal โชว์ชื่อคอลัมน์ดิบ (`location: 15310 → 15399`) ซึ่งอ่านไม่รู้เรื่อง
// สำหรับคนที่ไม่ได้เขียนโค้ด ครอบทั้ง key แบบ diff (changes) และ key แบบ flat ของ action อื่น
export const FIELD_LABEL = {
  // ลายเซ็นบนหน้าจอ (เฟส 11)
  staff_signed: 'เจ้าหน้าที่เซ็นกำกับ',
  kind: 'ชนิดลายเซ็น',
  name: 'ชื่อ',
  code: 'รหัส',
  manufacturer: 'ผู้ผลิต',
  model_number: 'รุ่น',
  serial_number: 'หมายเลขเครื่อง (SN)',
  item_type: 'ประเภท',
  location: 'สถานที่เก็บ',
  status: 'สถานะ',
  unit: 'หน่วยนับ',
  unit_value: 'มูลค่าแท้จริง (ราคาที่ซื้อ)',
  book_value_override: 'มูลค่าตามบัญชี (กรอกเอง)',
  acquired_at: 'วันที่ได้มา',
  useful_life_years: 'อายุการใช้งาน (ปี)',
  quantity_total: 'จำนวนทั้งหมด',
  quantity_available: 'คงเหลือ',
  low_stock_threshold: 'เกณฑ์แจ้งเตือนของใกล้หมด',
  is_borrowable: 'อนุญาตให้ยืม',
  category_ids: 'หมวดหมู่',
  description: 'คำอธิบาย',
  image_urls: 'รูปภาพ',
  // key แบบ flat ที่ action อื่นใช้
  quantity: 'จำนวน',
  reason: 'เหตุผล',
  added: 'จำนวนที่เพิ่ม',
  new_codes: 'รหัสใหม่',
  split_into: 'แยกเป็นรหัส',
  old_available: 'คงเหลือเดิม',
  new_available: 'คงเหลือใหม่',
  photo_urls: 'รูปหลักฐาน',
  file: 'ไฟล์ที่แนบ',
  source: 'นำเข้าจากไฟล์',
  count: 'จำนวนรายการ',
  delta: 'จำนวนที่ปรับ (+/-)',
  added: 'เพิ่มใหม่',
  updated: 'อัปเดต',
  approval_status: 'สถานะการอนุมัติ',
  generation: 'รุ่น / หมู่เรียน',
  advisor: 'อาจารย์ที่ปรึกษา',
  set: 'ค่าที่ตั้ง',
  pickup: 'นัดรับของ',
  equipment_ids: 'รายการที่แก้',
  request_code: 'เลขคำขอ',
  due_date: 'กำหนดคืน',
  condition: 'สภาพเมื่อคืน',
  item: 'รายการ',
  part_name: 'ชิ้นส่วน',
  replaces_part: 'มาแทนชิ้นส่วน',
  part_id: 'รหัสชิ้นส่วน',
  removed_at: 'วันที่ถอดออก',
  old_due_date: 'กำหนดคืนเดิม',
  new_due_date: 'กำหนดคืนใหม่',
  purpose: 'วัตถุประสงค์',
  requested_due_date: 'วันคืนที่ขอ',
  notify_time: 'เวลาส่งแจ้งเตือนรายวัน',
  items: 'รายการ',
  role: 'สิทธิ์',
  email: 'อีเมล',
  identifier: 'รหัสประจำตัว',
  is_active: 'เปิดใช้งาน',
  major: 'สาขา',
  full_name: 'ชื่อ',
  setting: 'ค่าที่แก้',
  durable_all: 'รับคืนครุภัณฑ์ทั้งหมด',
  fine_days_late: 'ล่าช้า (วัน)',
  fine_late_amount: 'ค่าปรับล่าช้า (บาท)',
  fine_damage_amount: 'ค่าเสียหาย (บาท)',
  amount: 'ยอด (บาท)',
  // อนุมัติบางชิ้น (เฟส 3) — ต้องอ่านออกว่าอนุมัติอะไรไป ไม่อนุมัติอะไรเพราะอะไร
  approved_items: 'รายการที่อนุมัติ',
  rejected_items: 'รายการที่ไม่อนุมัติ',
  // ค่าคุณภาพ + ชั้นปี (เฟส 10)
  event: 'เหตุการณ์',
  before: 'ก่อนประเมิน (%)',
  after: 'หลังประเมิน (%)',
  quality_tracked: 'ติดตามค่าคุณภาพ',
  quality_life_years: 'อายุการใช้งานที่ใช้คิดคุณภาพ (ปี)',
  affected_codes: 'รหัสหน่วยอื่นในรุ่นที่ได้รับผลด้วย',
  // แก้หลายรายการพร้อมกัน (bulk_update_equipment) แล้วเปลี่ยนชื่อ/ประเภทเข้ารุ่นที่ (ไม่) ติดตามคุณภาพอยู่
  // แล้ว — ผลข้างเคียงอัตโนมัติ 2 แบบที่เคยไม่โผล่ใน audit เลย (แก้ตามรีวิวรอบ 4, M-e)
  quality_inherited: 'สืบทอดค่าคุณภาพอัตโนมัติ (ย้ายเข้ารุ่นที่ติดตามอยู่แล้ว)',
  quality_auto_untracked: 'ปิดติดตามคุณภาพอัตโนมัติ (แปลงเป็นวัสดุสิ้นเปลือง)',
  enrollment_year: 'ปีที่เข้าศึกษา (พ.ศ.)',
  study_years: 'จำนวนปีที่ควรเรียนจบ',
  is_transfer: 'นักศึกษาเทียบโอน',
}

// เหตุการณ์การประเมินคุณภาพ (assess_quality.detail.event) — ค่าดิบอ่านไม่รู้เรื่อง
const QUALITY_EVENT_TH = {
  manual: 'ประเมินเอง', install_part: 'ติดตั้งชิ้นส่วน',
  repair_complete: 'ซ่อมเสร็จ', return_damaged: 'รับคืนแบบชำรุด', bulk: 'ประเมินทั้งรุ่น',
}

const STATUS_TH = {
  available: 'พร้อมให้ยืม', unavailable: 'ไม่อนุญาตให้ยืม', damaged: 'เสียหาย',
  under_repair: 'ซ่อมอยู่', retired: 'ปลดระวาง', borrowed: 'ถูกยืมอยู่',
}
const TYPE_TH = { durable: 'ครุภัณฑ์', material: 'วัสดุใช้ซ้ำ', consumable: 'วัสดุสิ้นเปลือง' }
// สภาพตอนรับคืน — เดิม log โชว์ค่าดิบ (ok / returned_full) ซึ่งคนนอกทีมอ่านไม่ออก
const CONDITION_TH = {
  ok: 'คืนปกติ', damaged: 'เสียหาย', lost: 'สูญหาย',
  returned_full: 'คืนครบ ไม่ได้ใช้', used_up: 'ใช้หมด', discarded: 'เสียหาย/ทิ้ง',
}

export const actionLabel = (a) => ACTION_LABEL[a] ?? a
export const fieldLabel = (f) => FIELD_LABEL[f] ?? f

/** ค่าที่อ่านง่าย — แปลง enum เป็นไทยตามชื่อฟิลด์ ถ้าไม่ใช่ enum ก็โชว์ตามเดิม */
export function fmtVal(v, field) {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.length ? v.map((x) => fmtVal(x, field)).join(', ') : '—'
  if (typeof v === 'boolean') return v ? 'ใช่' : 'ไม่ใช่'
  if (field === 'status') return STATUS_TH[v] ?? String(v)
  if (field === 'item_type') return TYPE_TH[v] ?? String(v)
  if (field === 'condition') return CONDITION_TH[v] ?? String(v)
  if (field === 'event') return QUALITY_EVENT_TH[v] ?? String(v)
  // วันที่ใน detail ถูกเก็บเป็น ISO (str(date)) — แสดงเป็น วว/ดด/ปปปป ให้ตรงกับที่อื่นทั้งระบบ
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) return formatDate(v)
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return formatDateTime(v)  // timestamp (removed_at ฯลฯ)
  // ผลกระทบรายแถวใน bulk (set.quality_inherited ฯลฯ): {code, ฟิลด์: [เดิม, ใหม่]} → "EQ-1 (ฟิลด์ เดิม → ใหม่)"
  if (typeof v === 'object' && v.code) {
    const diffs = Object.entries(v).filter(([k, d]) => k !== 'code' && Array.isArray(d))
      .map(([k, [a, b]]) => `${fieldLabel(k)} ${fmtVal(a, k)} → ${fmtVal(b, k)}`)
    return `${v.code} (${diffs.join(', ')})`
  }
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

// key ใน detail ที่ถูกใช้ประกอบ "ชื่อเป้าหมาย" ในประโยคแล้ว ไม่ต้องซ้ำในส่วนท้าย
const TARGET_KEYS = ['request_code', 'item', 'code', 'name', 'setting', 'setting_label',
                     'full_name', 'part_name', 'equipment_ids', 'part_id']

/** เป้าหมายของการกระทำในภาษาคน — อ่านจาก snapshot ใน detail ไม่ใช่ join ตาราง
 *  (แถวเป้าหมายอาจถูกลบไปแล้ว ประวัติต้องยังบอกได้ว่าทำกับอะไร) */
function targetPhrase(log) {
  const d = log.detail || {}
  if (d.request_code) return d.item ? `คำขอ ${d.request_code} · ${d.item}` : `คำขอ ${d.request_code}`
  if (d.setting_label || d.setting) return `ค่า "${d.setting_label || d.setting}"`
  if (d.part_name) return `ชิ้นส่วน ${d.part_name}`
  if (d.name || d.code) return [d.name, d.code ? `(${d.code})` : null].filter(Boolean).join(' ')
  if (d.full_name) return `บัญชี ${d.full_name}`
  return ''
}

/** log 1 แถว -> ประโยคไทยบรรทัดเดียวที่คนทั่วไป (ไม่ใช่ dev) อ่านรู้เรื่อง
 *  เช่น "สมชาย ใจดี (65010001) ยื่นคำขอยืม คำขอ REQ-2026-... — รายการ: โน้ตบุ๊ค ×1"
 *  ponytail: ตัดส่วนท้ายไว้ 3 ช่วง รายละเอียดครบ ๆ ดูได้ในโมดัลอยู่แล้ว */
/** บรรทัดแรก: ใคร ทำอะไร กับอะไร — สั้นพอให้กวาดตาอ่านทั้งตารางได้ */
export function logHeadline(log) {
  const who = log.actor_name
    ? `${log.actor_name}${log.actor_identifier ? ` (${log.actor_identifier})` : ''}`
    : 'ไม่ทราบผู้ทำ'
  return [`${who} ${actionLabel(log.action)}`, targetPhrase(log)].filter(Boolean).join(' ')
}

/** รายละเอียดของ log เป็น "ข้อความสั้นทีละอัน" — หน้าเว็บเอาไปขึ้นบรรทัดใหม่/แยกชิปได้
 *  เดิมต่อกันด้วย · ยาวเป็นพืดในบรรทัดเดียว พอมีรายการอนุมัติ 4 ชิ้นก็อ่านไม่ออกแล้ว */
export function logDetailChips(log) {
  return detailLines(log.detail)
    .filter((l) => !TARGET_KEYS.includes(l.field))
    .map((l) => (l.from !== undefined ? `${l.label}: ${l.from} → ${l.to}` : `${l.label}: ${l.to}`))
}

export function logSentence(log) {
  const who = log.actor_name
    ? `${log.actor_name}${log.actor_identifier ? ` (${log.actor_identifier})` : ''}`
    : 'ไม่ทราบผู้ทำ'
  const target = targetPhrase(log)
  const rest = detailLines(log.detail)
    .filter((l) => !TARGET_KEYS.includes(l.field))
    .map((l) => (l.from !== undefined ? `${l.label}: ${l.from} → ${l.to}` : `${l.label}: ${l.to}`))
  const tail = rest.slice(0, 3).join(' · ') + (rest.length > 3 ? ' …' : '')
  return [`${who} ${actionLabel(log.action)}`, target, tail && `— ${tail}`]
    .filter(Boolean).join(' ')
}

/** log 1 แถว -> รายการ "ฟิลด์: เดิม → ใหม่" หรือ "ฟิลด์: ค่า" สำหรับ action ที่ไม่ได้เก็บเป็น diff */
export function detailLines(detail) {
  if (!detail) return []
  if (detail.changes) {
    return Object.entries(detail.changes).map(([field, [from, to]]) => ({
      field, label: fieldLabel(field), from: fmtVal(from, field), to: fmtVal(to, field),
    }))
  }
  // "ผลกับทั้งรุ่น" ตอนแก้ quality_tracked/quality_life_years (update_equipment/bulk_update_equipment) —
  // เก็บ diff แบบเดียวกับ changes แต่คนละคีย์ (แยกจาก entry ปกติที่เป็นของหน่วยเดียวที่แอดมินแก้ตรง ๆ)
  // ต่อท้ายด้วย affected_codes (flat) ให้เห็นว่ากระทบหน่วยไหนบ้าง
  if (detail.quality_group_change) {
    const diffLines = Object.entries(detail.quality_group_change).map(([field, [from, to]]) => ({
      field, label: fieldLabel(field), from: fmtVal(from, field), to: fmtVal(to, field),
    }))
    const restLines = Object.entries(detail)
      .filter(([k]) => !['code', 'name', 'quality_group_change'].includes(k))
      .map(([field, v]) => ({ field, label: fieldLabel(field), to: fmtVal(v, field) }))
    return [...diffLines, ...restLines]
  }
  // bulk_update_equipment: ค่าที่ตั้งอยู่ใน detail.set — แตกเป็นทีละฟิลด์ ไม่งั้นขึ้นเป็น JSON ดิบก้อนเดียว
  if (detail.set) {
    const { set, ...rest } = detail
    return [...detailLines(rest),
      ...Object.entries(set).map(([field, v]) => ({ field, label: fieldLabel(field), to: fmtVal(v, field) }))]
  }
  // action แบบ flat (เพิ่ม/ปลดระวาง/ปรับยอด ฯลฯ) — ข้าม code/name เพราะหัวรายการบอกอยู่แล้ว
  return Object.entries(detail)
    .filter(([k]) => !['code', 'name'].includes(k))
    .map(([field, v]) => ({ field, label: fieldLabel(field), to: fmtVal(v, field) }))
}
