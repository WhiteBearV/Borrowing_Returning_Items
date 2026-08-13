import { useEffect, useState } from 'react'
import { bundleApi } from '../../api/bundleApi.js'
import { equipmentApi } from '../../api/equipmentApi.js'
import ConfirmModal from '../../components/common/ConfirmModal.jsx'

const errMsg = (err, fallback) => err?.response?.data?.detail ?? fallback

function BundleForm({ initial, onClose, onSave }) {
  const isEdit = Boolean(initial)
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [items, setItems] = useState(
    initial?.items.map((i) => ({ equipment_id: i.equipment_id, quantity: i.quantity, name: i.equipment_name })) ?? [],
  )
  const [triggerEquipmentId, setTriggerEquipmentId] = useState(initial?.trigger_equipment_id ?? '')
  const [search, setSearch] = useState('')
  const [results, setResults] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // ค้นหาอุปกรณ์มาใส่ชุด — debounce เบา ๆ กันยิง API ทุกตัวอักษร
  useEffect(() => {
    if (!search) { setResults([]); return }
    const t = setTimeout(() => {
      equipmentApi.list({ search, page_size: 8 }).then((d) => setResults(d.items)).catch(() => {})
    }, 300)
    return () => clearTimeout(t)
  }, [search])

  const add = (eq) => {
    if (items.some((i) => i.equipment_id === eq.id)) return
    setItems((prev) => [...prev, { equipment_id: eq.id, quantity: 1, name: eq.name }])
    setSearch('')
  }

  const submit = async (e) => {
    e.preventDefault()
    if (items.length === 0) { setError('เลือกอุปกรณ์อย่างน้อย 1 รายการ'); return }
    setError('')
    setLoading(true)
    try {
      // ตัวกระตุ้นต้องเป็นของในชุด — ถ้าถูกถอดออกไปแล้วให้ล้างเป็น null
      const trigger = items.some((i) => i.equipment_id === triggerEquipmentId) ? triggerEquipmentId : null
      const body = {
        name,
        description: description || undefined,
        trigger_equipment_id: trigger,
        items: items.map(({ equipment_id, quantity }) => ({ equipment_id, quantity: Number(quantity) })),
      }
      if (isEdit) await bundleApi.update(initial.id, body)
      else await bundleApi.create(body)
      onSave()
    } catch (err) {
      setError(errMsg(err, 'บันทึกไม่สำเร็จ'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4 overflow-y-auto py-8">
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl">
        <h2 className="font-bold text-gray-800 mb-4">{isEdit ? 'แก้ไขชุดอุปกรณ์' : 'สร้างชุดอุปกรณ์'}</h2>
        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">ชื่อชุด</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required
                   placeholder="เช่น ชุดคอมพิวเตอร์"
                   className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">คำอธิบาย</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)}
                   className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">อุปกรณ์ในชุด</label>
            <div className="space-y-1.5 mb-2">
              {items.map((it) => (
                <div key={it.equipment_id} className="flex items-center gap-2 text-sm">
                  <span className="flex-1 truncate text-gray-700">{it.name}</span>
                  <input type="number" min={1} value={it.quantity}
                         onChange={(e) => setItems((prev) => prev.map((p) =>
                           p.equipment_id === it.equipment_id ? { ...p, quantity: e.target.value } : p))}
                         className="w-16 rounded border border-gray-300 px-2 py-1 text-center" />
                  <button type="button" onClick={() => setItems((prev) => prev.filter((p) => p.equipment_id !== it.equipment_id))}
                          className="text-gray-300 hover:text-red-500 text-lg leading-none">×</button>
                </div>
              ))}
              {items.length === 0 && <p className="text-xs text-gray-400">ยังไม่มีอุปกรณ์ในชุด</p>}
            </div>
            <input value={search} onChange={(e) => setSearch(e.target.value)}
                   placeholder="ค้นหาอุปกรณ์เพื่อเพิ่ม…"
                   className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
            {results.length > 0 && (
              <div className="mt-1 rounded-lg border border-gray-200 divide-y max-h-40 overflow-y-auto">
                {results.map((eq) => (
                  <button key={eq.id} type="button" onClick={() => add(eq)}
                          className="block w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50">
                    {eq.name} <span className="text-xs text-gray-400">{eq.code}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              อุปกรณ์ตัวกระตุ้น <span className="text-gray-400">(กดเพิ่มตัวนี้ลงตะกร้าแล้วได้ทั้งชุด)</span>
            </label>
            <select value={triggerEquipmentId ?? ''} onChange={(e) => setTriggerEquipmentId(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white">
              <option value="">— ไม่ขยายอัตโนมัติ —</option>
              {items.map((it) => (
                <option key={it.equipment_id} value={it.equipment_id}>{it.name}</option>
              ))}
            </select>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-2 pt-1">
            <button type="button" onClick={onClose}
                    className="flex-1 rounded-lg border border-gray-300 py-2 text-sm">ยกเลิก</button>
            <button type="submit" disabled={loading}
                    className="flex-1 rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white disabled:opacity-50">
              {loading ? 'กำลังบันทึก…' : 'บันทึก'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function BundleManagePage() {
  const [bundles, setBundles] = useState([])
  const [editing, setEditing] = useState(undefined) // undefined = ปิด, null = สร้างใหม่
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    bundleApi.list().then(setBundles).catch(() => {}).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const toggleActive = async (b) => {
    // ส่ง trigger เดิมไปด้วย เพราะ backend เขียนทับค่าตัวกระตุ้นทุกครั้งที่ update
    await bundleApi.update(b.id, { is_active: !b.is_active, trigger_equipment_id: b.trigger_equipment_id ?? null })
    load()
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">ชุดอุปกรณ์</h1>
          <p className="text-sm text-gray-500 mt-0.5">ชุดเป็นทางลัดหยิบของใส่ตะกร้า นักศึกษาถอดของออกจากชุดได้เอง</p>
        </div>
        <button onClick={() => setEditing(null)}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
          + สร้างชุด
        </button>
      </div>

      {loading ? (
        <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
      ) : bundles.length === 0 ? (
        <p className="text-center text-gray-400 py-16">ยังไม่มีชุดอุปกรณ์</p>
      ) : (
        <div className="space-y-3">
          {bundles.map((b) => (
            <div key={b.id} className="bg-white rounded-xl border border-gray-200 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold text-gray-800">
                    {b.name}
                    {!b.is_active && <span className="ml-2 text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">ปิดใช้งาน</span>}
                  </p>
                  {b.description && <p className="text-sm text-gray-500">{b.description}</p>}
                </div>
                <div className="flex gap-3 text-sm shrink-0">
                  <button onClick={() => toggleActive(b)} className="text-gray-500 hover:text-gray-800">
                    {b.is_active ? 'ปิดใช้งาน' : 'เปิดใช้งาน'}
                  </button>
                  <button onClick={() => setEditing(b)} className="text-blue-600 hover:underline">แก้ไข</button>
                  <button onClick={() => setConfirmDelete(b)} className="text-red-500 hover:underline">ลบ</button>
                </div>
              </div>
              <ul className="mt-2 text-sm text-gray-600 space-y-0.5">
                {b.items.map((i) => (
                  <li key={i.equipment_id} className="flex gap-2">
                    <span className="text-gray-300">·</span>
                    <span className="flex-1 truncate">{i.equipment_name}</span>
                    <span className="text-gray-400">×{i.quantity} {i.unit ?? ''}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {editing !== undefined && (
        <BundleForm initial={editing} onClose={() => setEditing(undefined)}
                    onSave={() => { setEditing(undefined); load() }} />
      )}
      {confirmDelete && (
        <ConfirmModal
          title="ลบชุดอุปกรณ์"
          message={`ลบชุด "${confirmDelete.name}" ใช่หรือไม่ (ไม่กระทบคำขอที่ยืมไปแล้ว)`}
          onConfirm={async () => { await bundleApi.remove(confirmDelete.id); setConfirmDelete(null); load() }}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  )
}
