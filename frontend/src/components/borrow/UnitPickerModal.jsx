import { useEffect, useState } from 'react'
import { equipmentApi } from '../../api/equipmentApi.js'
import { formatDate } from '../../utils/formatDate.js'

/** เลือกหน่วยที่จะจ่ายเองตอนอนุมัติ — ปกติระบบเลือกให้อัตโนมัติ (ถูกใช้น้อยสุดก่อน หรือถ้ารุ่นนี้เปิดติดตาม
 *  คุณภาพ จับคู่อายุที่เหลือกับเวลาเรียนที่เหลือของผู้ยืม — ดู equipment_service.dispatch_order)
 *  แต่ของจริงบางทีต้องจ่ายเครื่องที่วางอยู่ตรงหน้าเคาน์เตอร์ แอดมินจึงต้องเลือกทับได้
 *  studentId (ไม่บังคับ): user_id ของผู้ยืม — ส่งไปให้ backend คำนวณ "แนะนำสำหรับผู้ยืมนี้" ด้วยกฎเดียวกับตอนอนุมัติจริง
 *  studentYearLabel (ไม่บังคับ): ป้ายชั้นปีผู้ยืม โชว์ในหัวโมดัลเฉย ๆ ไม่ใช้คำนวณอะไรฝั่งนี้ */
export default function UnitPickerModal({ item, selectedId, studentId, studentYearLabel, onPick, onClose }) {
  const [units, setUnits] = useState(null)
  const [recommendedId, setRecommendedId] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    equipmentApi.getGrouped(item.equipment_id, studentId)
      .then((g) => {
        const recommendedId = g.recommended_unit_id ?? null
        // หน่วยที่ระบบแนะนำ (จับคู่คุณภาพ↔เวลาเรียนที่เหลือถ้ารุ่นนี้เปิดติดตามคุณภาพ ไม่งั้นถูกใช้น้อยสุด
        // ก่อน — ดู equipment_service.dispatch_order) ต้องอยู่บนสุดเสมอ ไม่ใช่แค่มีป้าย "แนะนำ" ติดอยู่กลาง/
        // ท้ายลิสต์ — เรียงตาม days_borrowed เป็นแค่ fallback ของหน่วยที่เหลือ (แก้ตามรีวิวรอบ 3, MINOR-10)
        const members = [...(g.members ?? [])].sort((a, b) => {
          if (a.id === recommendedId) return -1
          if (b.id === recommendedId) return 1
          return a.days_borrowed - b.days_borrowed
        })
        setUnits(members)
        setRecommendedId(recommendedId)
      })
      .catch((e) => setError(e.response?.data?.detail ?? 'โหลดรายการหน่วยไม่สำเร็จ'))
  }, [item.equipment_id, studentId])

  const available = (u) => u.is_borrowable && u.status === 'available' && u.quantity_available >= item.quantity

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-lg shadow-xl space-y-3 max-h-[80vh] flex flex-col">
        <div>
          <h2 className="font-bold text-gray-800">เลือกหน่วยที่จะจ่าย</h2>
          <p className="text-sm text-gray-500">
            {item.equipment_name} — หน่วยแนะนำอยู่บนสุด ที่เหลือเรียงจากถูกใช้น้อยสุด
            {studentYearLabel && <span className="text-gray-400"> · ผู้ยืม: {studentYearLabel}</span>}
          </p>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        {!units && !error && <p className="text-sm text-gray-400">กำลังโหลด…</p>}

        <div className="overflow-y-auto divide-y divide-gray-100 rounded-lg border border-gray-100">
          {units?.map((u) => (
            <button
              key={u.id} type="button" disabled={!available(u)}
              onClick={() => onPick(u.id, u.code)}
              className={`w-full text-left px-3 py-2 flex items-center justify-between gap-3 text-sm
                ${!available(u) ? 'opacity-40 cursor-not-allowed'
                  : selectedId === u.id ? 'bg-primary-50' : 'hover:bg-gray-50'}`}
            >
              <span className="min-w-0">
                <span className="font-mono text-xs text-gray-500">{u.code}</span>
                {u.id === recommendedId && (
                  <span className="ml-1.5 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                    แนะนำสำหรับผู้ยืมนี้
                  </span>
                )}
                <span className="block text-xs text-gray-400">
                  ถูกใช้มาแล้ว {u.days_borrowed.toLocaleString('th-TH')} วัน
                  {u.acquired_at ? ` · ได้มา ${formatDate(u.acquired_at)}` : ''}
                  {/* ค่าคุณภาพ (เฟส 10) — มีค่าเฉพาะรุ่นที่เปิดติดตาม (backend เติมให้เจ้าหน้าที่เท่านั้นอยู่แล้ว) */}
                  {u.quality_tracked && u.current_quality != null &&
                    ` · คุณภาพ ${u.current_quality}%${u.quality_remaining_life_years != null ? ` (เหลือ ${u.quality_remaining_life_years} ปี)` : ''}`}
                  {u.quality_tracked && u.current_quality == null && ' · ยังไม่ประเมิน'}
                  {!available(u) ? ' · ไม่ว่าง' : ''}
                </span>
              </span>
              {selectedId === u.id && <span className="text-primary-600 text-xs font-semibold shrink-0">เลือกไว้</span>}
            </button>
          ))}
        </div>

        <div className="flex gap-3 pt-1">
          <button onClick={onClose}
            className="flex-1 rounded-full border py-2 text-sm text-gray-600 hover:bg-gray-50">ปิด</button>
          <button onClick={() => onPick(null, null)}
            className="flex-1 rounded-full border border-primary-300 py-2 text-sm text-primary-700 hover:bg-primary-50">
            ให้ระบบเลือกให้
          </button>
        </div>
      </div>
    </div>
  )
}
