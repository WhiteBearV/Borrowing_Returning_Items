/** รหัสหน่วย + ป้ายที่มาของบรรทัด — บรรทัดที่เกิดจากคืนบางส่วน/เปลี่ยนตัวระหว่างยืมมีชื่อรุ่นเดียวกับบรรทัดเดิม
 *  ถ้าไม่มีป้ายจะแยกไม่ออกว่าบรรทัดไหนเป็นเครื่องไหน (items = รายการทั้งใบ ใช้หาว่าบรรทัดนี้ถูกเปลี่ยนตัวออกไปหรือยัง) */
export default function ItemLineTag({ item, items = [], className = '' }) {
  const replacedBy = items.find((i) => i.swapped_from_id === item.id)
  const source = item.swapped_from_id && items.find((i) => i.id === item.swapped_from_id)
  const tag = item.swapped_from_id
    ? { text: 'เครื่องที่มาแทน', cls: 'bg-sky-50 text-sky-700', title: source?.equipment_code && `แทน ${source.equipment_code}` }
    : replacedBy
      ? { text: 'เปลี่ยนตัวออกแล้ว', cls: 'bg-gray-100 text-gray-500', title: replacedBy.equipment_code && `เปลี่ยนเป็น ${replacedBy.equipment_code}` }
      : item.split_from_id
        ? { text: 'คืนบางส่วน', cls: 'bg-violet-50 text-violet-700', title: 'ส่วนที่รับคืนไปก่อนจากรายการเดียวกัน' }
        : null
  // รหัสหน่วยเจาะจงยังไม่นิ่งจนกว่าจะอนุมัติ (ระบบเลือกหน่วยใหม่ได้ตอนอนุมัติ) — โชว์เฉพาะชิ้นที่ผ่านการอนุมัติแล้ว
  const code = item.item_status !== 'pending' ? item.equipment_code : null
  const asset = item.item_status !== 'pending' ? item.equipment_asset_number : null
  if (!code && !tag) return null
  return (
    <span className={`inline-flex items-center gap-1.5 align-middle ${className}`}>
      {code && <span className="font-mono text-xs text-gray-400">{code}</span>}
      {asset && <span className="font-mono text-[10px] text-gray-400" title="เลขครุภัณฑ์">({asset})</span>}
      {tag && <span title={tag.title || undefined} className={`text-[10px] px-1.5 py-0.5 rounded ${tag.cls}`}>{tag.text}</span>}
    </span>
  )
}
