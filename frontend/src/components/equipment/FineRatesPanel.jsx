import { useEffect, useState } from 'react'
import { fineRateApi } from '../../api/fineRateApi.js'
import { fineMoney } from '../../utils/fine.js'

const inputCls = 'rounded-lg border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500'

/** ป้ายอัตราค่าปรับคืนเกินกำหนดรายรุ่น (หน้าการตั้งค่า) — เจ้าหน้าที่ดูได้ · ผู้ดูแลสูงสุดเพิ่ม/แก้/ลบ/ตั้งค่าเริ่มต้น
 *  แก้ราคาป้ายมีผลกับการอนุมัติครั้งถัดไปเท่านั้น (ของที่ยืมอยู่ล็อกอัตราไว้ตอนอนุมัติแล้ว) */
export default function FineRatesPanel({ canEdit }) {
  const [rates, setRates] = useState([])
  const [edit, setEdit] = useState(null) // { id?, name, amount_per_day } — id ว่าง = เพิ่มใหม่
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => fineRateApi.list().then(setRates).catch(() => {})
  useEffect(() => { load() }, [])

  const run = async (fn) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      setEdit(null)
      await load()
    } catch (e) {
      setError(e.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
    } finally {
      setBusy(false)
    }
  }

  const save = () => run(() => {
    const data = { name: edit.name.trim(), amount_per_day: Number(edit.amount_per_day) }
    return edit.id ? fineRateApi.update(edit.id, data) : fineRateApi.create(data)
  })
  const valid = edit && edit.name.trim() && edit.amount_per_day !== '' && Number(edit.amount_per_day) >= 0

  return (
    <section>
      <h2 className="text-sm font-semibold text-gray-600 mb-1">ป้ายอัตราค่าปรับคืนเกินกำหนด (รายรุ่น)</h2>
      <p className="mb-2 text-xs text-gray-500">
        เจ้าหน้าที่เลือกป้ายให้อุปกรณ์ได้ที่ฟอร์มอุปกรณ์ (มีผลทั้งรุ่น) · อัตราถูกล็อกตอนอนุมัติ แก้ราคาป้ายแล้วมีผลกับการยืมครั้งถัดไปเท่านั้น
        · รุ่นใหม่ได้ป้าย "ค่าเริ่มต้น"
      </p>
      {error && <p className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
      <div className="bg-white rounded-xl border border-gray-200 divide-y">
        {rates.map((r) => (
          <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
            {edit?.id === r.id ? (
              <div className="flex flex-wrap items-center gap-2">
                <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} className={`${inputCls} w-44`} />
                <input type="number" min="0" step="0.01" value={edit.amount_per_day}
                  onChange={(e) => setEdit({ ...edit, amount_per_day: e.target.value })} className={`${inputCls} w-24`} />
                <span className="text-sm text-gray-500">บาท/วัน</span>
              </div>
            ) : (
              <div className="text-sm text-gray-800">
                <span className="font-medium">{r.name}</span>
                <span className="ml-2 text-gray-500">{fineMoney(r.amount_per_day)} บาท/วัน · ใช้กับ {r.model_count} รุ่น</span>
                {r.is_default && <span className="ml-2 rounded-full bg-primary-100 px-2 py-0.5 text-xs font-medium text-primary-700">ค่าเริ่มต้น</span>}
              </div>
            )}
            {canEdit && (
              <div className="flex gap-3 text-xs">
                {edit?.id === r.id ? (
                  <>
                    <button onClick={save} disabled={!valid || busy} className="font-medium text-primary-600 hover:underline disabled:opacity-50">บันทึก</button>
                    <button onClick={() => setEdit(null)} className="text-gray-500 hover:underline">ยกเลิก</button>
                  </>
                ) : (
                  <>
                    <button onClick={() => setEdit({ id: r.id, name: r.name, amount_per_day: r.amount_per_day })} className="text-primary-600 hover:underline">แก้ไข</button>
                    {!r.is_default && (
                      <button onClick={() => run(() => fineRateApi.update(r.id, { is_default: true }))} className="text-gray-600 hover:underline">ตั้งเป็นค่าเริ่มต้น</button>
                    )}
                    {!r.is_default && (
                      <button onClick={() => run(() => fineRateApi.remove(r.id))} className="text-red-600 hover:underline">ลบ</button>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        ))}
        {canEdit && (
          <div className="flex flex-wrap items-center gap-2 px-4 py-2.5">
            {edit && !edit.id ? (
              <>
                <input autoFocus value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })}
                  placeholder="ชื่อป้าย เช่น อุปกรณ์ราคาสูง" className={`${inputCls} w-52`} />
                <input type="number" min="0" step="0.01" value={edit.amount_per_day}
                  onChange={(e) => setEdit({ ...edit, amount_per_day: e.target.value })} placeholder="บาท/วัน" className={`${inputCls} w-24`} />
                <button onClick={save} disabled={!valid || busy}
                  className="rounded-full bg-primary-600 px-4 py-1 text-xs font-semibold text-white hover:bg-primary-700 disabled:opacity-50">เพิ่ม</button>
                <button onClick={() => setEdit(null)} className="text-xs text-gray-500 hover:underline">ยกเลิก</button>
              </>
            ) : (
              <button onClick={() => setEdit({ name: '', amount_per_day: '' })} className="text-sm font-medium text-primary-600 hover:underline">
                + เพิ่มป้ายอัตราใหม่
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
