import { useEffect, useState } from 'react'
import { equipmentApi } from '../../api/equipmentApi.js'
import ConfirmModal from '../../components/common/ConfirmModal.jsx'
import Pagination from '../../components/common/Pagination.jsx'

const EMPTY_FORM = { code: '', name: '', category_ids: [], item_type: 'durable', description: '', location: '', unit: '', quantity_total: 1, image_urls: [] }

const IMG_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const imageSrc = (url) => (url?.startsWith('/') ? `${IMG_BASE}${url}` : url)

// FastAPI 422 คืน detail เป็น array ของ object — บังคับให้ได้ string เสมอ กัน React crash
const errMsg = (err, fallback) => {
  const d = err.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((e) => e.msg).join(', ')
  return fallback
}

function EquipmentModal({ initial, categories, onClose, onSave }) {
  const isEdit = !!initial?.id
  const [form, setForm] = useState(
    isEdit
      ? { ...initial, image_urls: initial.image_urls ?? (initial.image_url ? [initial.image_url] : []), category_ids: (initial.categories ?? []).map((c) => c.id) }
      : EMPTY_FORM,
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)

  const uploadImage = async (e) => {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    e.target.value = ''  // reset ให้เลือกไฟล์เดิมซ้ำได้
    setError('')
    setUploading(true)
    try {
      const results = await Promise.all(files.map((file) => equipmentApi.uploadImage(file)))
      setForm((f) => ({ ...f, image_urls: [...f.image_urls, ...results.map((r) => r.image_url)] }))
    } catch (err) {
      setError(errMsg(err, 'อัปโหลดรูปไม่สำเร็จ'))
    } finally {
      setUploading(false)
    }
  }

  const removeImage = (url) => setForm((f) => ({ ...f, image_urls: f.image_urls.filter((u) => u !== url) }))

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const toggleCategory = (id) =>
    setForm((f) => ({
      ...f,
      category_ids: f.category_ids.includes(id)
        ? f.category_ids.filter((c) => c !== id)
        : [...f.category_ids, id],
    }))

  const submit = async (e) => {
    e.preventDefault()
    if (form.category_ids.length === 0) { setError('เลือกหมวดหมู่อย่างน้อย 1 หมวด'); return }
    setError('')
    setLoading(true)
    try {
      const payload = {
        ...form,
        quantity_total: Number(form.quantity_total),
        description: form.description || undefined,
        location: form.location || undefined,
        unit: form.unit || undefined,
        image_urls: form.image_urls,
      }
      if (isEdit) {
        await equipmentApi.update(initial.id, payload)
      } else {
        await equipmentApi.create(payload)
      }
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
        <h2 className="font-bold text-gray-800 mb-4">{isEdit ? 'แก้ไขอุปกรณ์' : 'เพิ่มอุปกรณ์ใหม่'}</h2>
        {error && <p className="mb-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
        <form onSubmit={submit} className="space-y-3">
          {[
            { label: 'รหัสอุปกรณ์ *', key: 'code', required: true, disabled: isEdit },
            { label: 'ชื่ออุปกรณ์ *', key: 'name', required: true },
            { label: 'สถานที่เก็บ', key: 'location' },
          ].map(({ label, key, required, disabled, placeholder }) => (
            <div key={key}>
              <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
              <input type="text" required={required} disabled={disabled} value={form[key]} onChange={set(key)}
                placeholder={placeholder}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-400" />
            </div>
          ))}

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              รูปภาพ {form.image_urls.length > 0 && <span className="text-gray-400">({form.image_urls.length} รูป · รูปแรก = ปก)</span>}
            </label>
            {form.image_urls.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {form.image_urls.map((url, i) => (
                  <div key={url} className="relative group">
                    <img src={imageSrc(url)} alt="" className="w-16 h-16 rounded-lg object-cover border border-gray-200" />
                    {i === 0 && <span className="absolute bottom-0 inset-x-0 bg-blue-600/80 text-white text-[10px] text-center rounded-b-lg">ปก</span>}
                    <button type="button" onClick={() => removeImage(url)}
                      className="absolute -top-1.5 -right-1.5 bg-red-500 text-white rounded-full w-5 h-5 text-xs leading-none flex items-center justify-center shadow hover:bg-red-600">×</button>
                  </div>
                ))}
              </div>
            )}
            <input type="file" accept="image/*" multiple onChange={uploadImage} disabled={uploading}
              className="block w-full text-xs text-gray-500 file:mr-2 file:rounded-lg file:border-0 file:bg-blue-50 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-blue-700 hover:file:bg-blue-100" />
            {uploading && <p className="mt-1 text-xs text-gray-400">กำลังอัปโหลด…</p>}
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">หมวดหมู่ * (เลือกได้หลายหมวด)</label>
            <div className="flex flex-wrap gap-1.5 rounded-lg border border-gray-300 p-2 max-h-32 overflow-y-auto">
              {categories.map((c) => {
                const on = form.category_ids.includes(c.id)
                return (
                  <button type="button" key={c.id} onClick={() => toggleCategory(c.id)}
                    className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                      on ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}>
                    {c.name}
                  </button>
                )
              })}
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">ประเภท *</label>
            <select value={form.item_type} onChange={set('item_type')} disabled={isEdit}
              className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50">
              <option value="durable">ครุภัณฑ์</option>
              <option value="consumable">วัสดุสิ้นเปลือง</option>
            </select>
          </div>

          {isEdit && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">สถานะ</label>
              <select value={form.status} onChange={set('status')}
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="available">พร้อมให้ยืม</option>
                <option value="unavailable">ไม่อนุญาตให้ยืม</option>
                <option value="damaged">เสียหาย</option>
                <option value="under_repair">ซ่อมอยู่</option>
                <option value="retired">ปลดระวาง</option>
              </select>
            </div>
          )}

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
  const [showCats, setShowCats] = useState(false)

  const reloadCategories = () => equipmentApi.listCategories().then(setCategories).catch(() => {})

  const load = () => {
    setLoading(true)
    equipmentApi.list({
      search: search || undefined,
      category_id: filterCategory || undefined,
      item_type: filterType || undefined,
      page, page_size: 15,
    }).then(setData).finally(() => setLoading(false))
  }

  useEffect(() => { reloadCategories() }, [])
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

  const STATUS_STYLE = { available: 'text-green-600', borrowed: 'text-blue-600', under_repair: 'text-yellow-600', damaged: 'text-red-500', retired: 'text-gray-400', unavailable: 'text-gray-500' }
  const STATUS_LABEL = { available: 'พร้อม', borrowed: 'ถูกยืม', under_repair: 'ซ่อม', damaged: 'เสียหาย', retired: 'ปลดระวาง', unavailable: 'ไม่อนุญาตให้ยืม' }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">จัดการอุปกรณ์</h1>
        <div className="flex gap-2">
          <button onClick={() => setShowCats(true)}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            จัดการหมวดหมู่
          </button>
          <button onClick={() => setModal('create')}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
            + เพิ่มอุปกรณ์
          </button>
        </div>
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
                {['รูป', 'รหัส', 'ชื่อ', 'หมวดหมู่', 'ประเภท', 'คงเหลือ', 'สถานะ', ''].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((eq) => (
                <tr key={eq.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2">
                    {eq.image_url
                      ? <img src={imageSrc(eq.image_url)} alt="" className="w-10 h-10 rounded object-cover border border-gray-200" />
                      : <div className="w-10 h-10 rounded bg-gray-100 border border-gray-200 flex items-center justify-center text-gray-300">🖼</div>}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-500">{eq.code}</td>
                  <td className="px-4 py-2.5 font-medium text-gray-800">{eq.name}</td>
                  <td className="px-4 py-2.5 text-gray-500 text-xs">{(eq.categories ?? []).map((c) => c.name).join(', ') || '—'}</td>
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

      {showCats && (
        <CategoryModal
          categories={categories}
          onClose={() => { setShowCats(false); load() }}
          onChanged={reloadCategories}
        />
      )}
    </div>
  )
}

function CategoryModal({ categories, onClose, onChanged }) {
  const [newName, setNewName] = useState('')
  const [editing, setEditing] = useState(null) // { id, name }
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const run = async (fn) => {
    setError('')
    setBusy(true)
    try { await fn(); await onChanged() }
    catch (err) { setError(errMsg(err, 'ทำรายการไม่สำเร็จ')) }
    finally { setBusy(false) }
  }

  const add = (e) => {
    e.preventDefault()
    if (!newName.trim()) return
    run(async () => { await equipmentApi.createCategory({ name: newName.trim() }); setNewName('') })
  }
  const saveEdit = () => run(async () => {
    await equipmentApi.updateCategory(editing.id, { name: editing.name.trim() })
    setEditing(null)
  })
  const remove = (c) => run(() => equipmentApi.deleteCategory(c.id))

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl">
        <h2 className="font-bold text-gray-800 mb-4">จัดการหมวดหมู่</h2>
        {error && <p className="mb-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

        <form onSubmit={add} className="flex gap-2 mb-4">
          <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="ชื่อหมวดหมู่ใหม่"
            className="flex-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <button type="submit" disabled={busy}
            className="rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">เพิ่ม</button>
        </form>

        <div className="max-h-72 overflow-y-auto divide-y divide-gray-100">
          {categories.map((c) => (
            <div key={c.id} className="flex items-center gap-2 py-2">
              {editing?.id === c.id ? (
                <>
                  <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                    className="flex-1 rounded-lg border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  <button onClick={saveEdit} disabled={busy} className="text-xs text-blue-600 hover:underline">บันทึก</button>
                  <button onClick={() => setEditing(null)} className="text-xs text-gray-400 hover:underline">ยกเลิก</button>
                </>
              ) : (
                <>
                  <span className="flex-1 text-sm text-gray-700">{c.name}</span>
                  <button onClick={() => setEditing({ id: c.id, name: c.name })} className="text-xs text-blue-600 hover:underline">แก้ไข</button>
                  <button onClick={() => remove(c)} disabled={busy} className="text-xs text-red-500 hover:underline">ลบ</button>
                </>
              )}
            </div>
          ))}
          {categories.length === 0 && <p className="text-center text-gray-400 py-6 text-sm">ยังไม่มีหมวดหมู่</p>}
        </div>

        <button onClick={onClose} className="mt-4 w-full rounded-lg border py-2 text-sm text-gray-600 hover:bg-gray-50">ปิด</button>
      </div>
    </div>
  )
}
