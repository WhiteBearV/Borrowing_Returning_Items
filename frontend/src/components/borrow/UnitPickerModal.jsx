import { useEffect, useState } from 'react'
import { equipmentApi } from '../../api/equipmentApi.js'
import { formatDate } from '../../utils/formatDate.js'

/** เลือกหน่วยที่จะจ่ายเองตอนอนุมัติ — ปกติระบบเลือก "หน่วยที่ถูกใช้มาน้อยสุด" ให้อัตโนมัติ
 *  แต่ของจริงบางทีต้องจ่ายเครื่องที่วางอยู่ตรงหน้าเคาน์เตอร์ แอดมินจึงต้องเลือกทับได้
 *  ตัวเลข "ถูกใช้ไปแล้วกี่วัน" คือเกณฑ์เดียวกับที่ระบบใช้เรียง จะได้เห็นว่าทำไมระบบเลือกชิ้นนั้น */
export default function UnitPickerModal({ item, selectedId, onPick, onClose }) {
  const [units, setUnits] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    equipmentApi.getGrouped(item.equipment_id)
      .then((g) => setUnits([...(g.members ?? [])].sort((a, b) => a.days_borrowed - b.days_borrowed)))
      .catch((e) => setError(e.response?.data?.detail ?? 'โหลดรายการหน่วยไม่สำเร็จ'))
  }, [item.equipment_id])

  const available = (u) => u.is_borrowable && u.status === 'available' && u.quantity_available >= item.quantity

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-lg shadow-xl space-y-3 max-h-[80vh] flex flex-col">
        <div>
          <h2 className="font-bold text-gray-800">เลือกหน่วยที่จะจ่าย</h2>
          <p className="text-sm text-gray-500">{item.equipment_name} — เรียงจากหน่วยที่ถูกใช้มาน้อยสุด</p>
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
                <span className="block text-xs text-gray-400">
                  ถูกใช้มาแล้ว {u.days_borrowed.toLocaleString('th-TH')} วัน
                  {u.acquired_at ? ` · ได้มา ${formatDate(u.acquired_at)}` : ''}
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
