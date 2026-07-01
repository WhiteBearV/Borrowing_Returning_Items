import { useEffect, useState } from 'react'
import { equipmentApi } from '../../api/equipmentApi.js'
import ConfirmModal from '../../components/common/ConfirmModal.jsx'
import Pagination from '../../components/common/Pagination.jsx'

const EMPTY_FORM = { code: '', name: '', category_id: '', item_type: 'durable', description: '', location: '', unit: '', quantity_total: 1, image_url: '' }

function EquipmentModal({ initial, categories, onClose, onSave }) {
  const isEdit = !!initial?.id
  const [form, setForm] = useState(isEdit ? { ...initial, image_url: initial.image_url ?? '' } : EMPTY_FORM)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const payload = {
        ...form,
        quantity_total: Number(form.quantity_total),
        description: form.description || undefined,
        location: form.location || undefined,
        unit: form.unit || undefined,
        image_url: form.image_url || undefined,
      }
      if (isEdit) {
        await equipmentApi.update(initial.id, payload)
      } else {
        await equipmentApi.create(payload)
      }
      onSave()
    } catch (err) {
      setError(err.response?.data?.detail ?? 'บันทึกไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4 overflow-y-auto py-8">
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl">
        <h2 className="font-bold text-gray-800 mb-4">{isEdit ? 'แก้ไขอุปกรณ์' : 'เพิ่มอุปกรณ์ใหม่'}</h2>
        {error && <p className="mb-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <form onSubmit={submit} className="space-y-3">
          {[
            { label: 'รหัสอุปกรณ์ *', key: 'code', required: true, disabled: isEdit },
            { label: 'ชื่ออุปกรณ์ *', key: 'name', required: true },
            { label: 'สถานที่เก็บ', key: 'location' },
            { label: 'URL รูปภาพ', key: 'image_url', placeholder: 'https://…' },
          ].map(({ label, key, required, disabled, placeholder }) => (
            <div key={key}>
              <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
              <input type="text" required={required} disabled={disabled} value={form[key]} onChange={set(key)}
                placeholder={placeholder}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-400" />
            </div>
          ))}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">หมวดหมู่ *</label>
              <select required value={form.category_id} onChange={set('category_id')}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">— เลือก —</option>
                {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">ประเภท *</label>
              <select value={form.item_type} onChange={set('item_type')} disabled={isEdit}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50">
                <option value="durable">ครุภัณฑ์</option>
                <option value="consumable">วัสดุสิ้นเปลือง</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">จำนวนทั้งหมด *</label>
              <input type="number" min={1} required value={form.quantity_total} onChange={set('quantity_total')}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            {form.item_type === 'consumable' && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">หน่วย</label>
                <input type="text" value={form.unit} onChange={set('unit')} placeholder="ชิ้น / ก้อน…"
                  className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">คำอธิบาย</label>
            <textarea rows={2} value={form.description} onChange={set('description')}
              className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 rounded-lg border py-2 text-sm text-gray-600 hover:bg-gray-50">ยกเลิก</button>
            <button type="submit" disabled={loading}
              className="flex-1 rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
              {loading ? 'กำลังบันทึก…' : 'บันทึก'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function EquipmentManagePage() {
  const [data, setData] = useState({ items: [], total: 0 })
  const [categories, setCategories] = useState([])
  const [search, setSearch] = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [filterType, setFilterType] = useState('')
  const [page, setPage] = useState(1)
  const [modal, setModal] = useState(null) // null | 'create' | equipment object
  const [confirm, setConfirm] = useState(null) // { title, message, onConfirm }
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    equipmentApi.list({
      search: search || undefined,
      category_id: filterCategory || undefined,
      item_type: filterType || undefined,
      page, page_size: 15,
    }).then(setData).finally(() => setLoading(false))
  }

  useEffect(() => { equipmentApi.listCategories().then(setCategories).catch(() => {}) }, [])
  useEffect(() => { load() }, [search, filterCategory, filterType, page])

  const retire = (id, name) => setConfirm({
    title: 'ปลดระวางอุปกรณ์',
    message: `ปลดระวาง "${name}" ?\nอุปกรณ์จะไม่สามารถยืมได้อีก`,
    confirmLabel: 'ปลดระวาง',
    danger: true,
    onConfirm: async () => { setConfirm(null); await equipmentApi.retire(id); load() },
  })

  const deletePermanent = (id, name) => setConfirm({
    title: 'ลบอุปกรณ์ถาวร',
    message: `ลบ "${name}" ออกจากระบบถาวร?\n(ทำได้เฉพาะอุปกรณ์ที่ไม่มีประวัติการยืม)`,
    confirmLabel: 'ลบถาวร',
    danger: true,
    onConfirm: async () => { setConfirm(null); await equipmentApi.deletePermanent(id); load() },
  })

  const STATUS_STYLE = { available: 'text-green-600', borrowed: 'text-blue-600', under_repair: 'text-yellow-600', damaged: 'text-red-500', retired: 'text-gray-400' }
  const STATUS_LABEL = { available: 'พร้อม', borrowed: 'ถูกยืม', under_repair: 'ซ่อม', damaged: 'เสียหาย', retired: 'ปลดระวาง' }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">จัดการอุปกรณ์</h1>
        <button onClick={() => setModal('create')}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
          + เพิ่มอุปกรณ์
        </button>
      </div>

      <div className="flex gap-3 mb-4">
        <input type="text" placeholder="ค้นหาชื่อหรือรหัสอุปกรณ์…" value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1) }}
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        <select value={filterCategory} onChange={(e) => { setFilterCategory(e.target.value); setPage(1) }}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">ทุกหมวดหมู่</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={filterType} onChange={(e) => { setFilterType(e.target.value); setPage(1) }}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">ทุกประเภท</option>
          <option value="durable">ครุภัณฑ์</option>
          <option value="consumable">วัสดุสิ้นเปลือง</option>
        </select>
      </div>

      {loading ? (
        <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['รหัส', 'ชื่อ', 'ประเภท', 'คงเหลือ', 'สถานะ', ''].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((eq) => (
                <tr key={eq.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-500">{eq.code}</td>
                  <td className="px-4 py-2.5 font-medium text-gray-800">{eq.name}</td>
                  <td className="px-4 py-2.5 text-gray-500">{eq.item_type === 'durable' ? 'ครุภัณฑ์' : 'สิ้นเปลือง'}</td>
                  <td className="px-4 py-2.5 text-gray-600">{eq.quantity_available}/{eq.quantity_total} {eq.unit ?? ''}</td>
                  <td className={`px-4 py-2.5 font-medium ${STATUS_STYLE[eq.status] ?? ''}`}>{STATUS_LABEL[eq.status] ?? eq.status}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex gap-3">
                      <button onClick={() => setModal(eq)} className="text-xs text-blue-600 hover:underline">แก้ไข</button>
                      {eq.status !== 'retired' && (
                        <button onClick={() => retire(eq.id, eq.name)} className="text-xs text-orange-500 hover:underline">ปลดระวาง</button>
                      )}
                      {eq.status === 'retired' && (
                        <button onClick={() => deletePermanent(eq.id, eq.name)} className="text-xs text-red-600 hover:underline font-medium">ลบถาวร</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.items.length === 0 && <p className="text-center text-gray-400 py-10">ไม่พบอุปกรณ์</p>}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={15} onChange={setPage} />

      {modal && (
        <EquipmentModal
          initial={modal === 'create' ? null : modal}
          categories={categories}
          onClose={() => setModal(null)}
          onSave={() => { setModal(null); load() }}
        />
      )}

      {confirm && (
        <ConfirmModal
          title={confirm.title}
          message={confirm.message}
          confirmLabel={confirm.confirmLabel}
          danger={confirm.danger}
          onConfirm={confirm.onConfirm}
          onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  )
}
