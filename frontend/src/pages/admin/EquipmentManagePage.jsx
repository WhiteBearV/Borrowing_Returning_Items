import { Fragment, useEffect, useState } from 'react'
import { equipmentApi } from '../../api/equipmentApi.js'
import { useAuthContext } from '../../context/AuthContext.jsx'
import ConfirmModal from '../../components/common/ConfirmModal.jsx'
import Pagination from '../../components/common/Pagination.jsx'
import { openPdf } from '../../utils/openPdf.js'

const EMPTY_FORM = { code: '', name: '', category_ids: [], item_type: 'durable', description: '', location: '', unit: '', unit_value: '', quantity_total: 1, image_urls: [], is_borrowable: true }

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
    // บังคับรูปเฉพาะตอนเพิ่มใหม่ ของเดิมที่นำเข้าจากทะเบียนยังไม่มีรูป ต้องแก้ไขได้อยู่
    if (!isEdit && form.image_urls.length === 0) { setError('แนบรูปอุปกรณ์อย่างน้อย 1 รูป'); return }
    setError('')
    setLoading(true)
    try {
      const payload = {
        ...form,
        quantity_total: Number(form.quantity_total),
        description: form.description || undefined,
        location: form.location || undefined,
        unit: form.unit || undefined,
        unit_value: form.unit_value === '' || form.unit_value == null ? undefined : Number(form.unit_value),
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
              <option value="material">วัสดุ</option>
              <option value="consumable">วัสดุสิ้นเปลือง</option>
            </select>
          </div>

          <label className="flex items-start gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
            <input type="checkbox" checked={!form.is_borrowable} className="mt-0.5"
              onChange={(e) => setForm({ ...form, is_borrowable: !e.target.checked })} />
            <span className="text-xs text-gray-600">
              <span className="font-medium text-gray-700">ของประจำห้อง — ห้ามยืมออก</span>
              <br />เช่น โต๊ะ ตู้ ทีวี เครื่องที่ติดตั้งประจำที่ — นักศึกษาจะเห็นแต่ยืมไม่ได้
            </span>
          </label>

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
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">มูลค่า/ชิ้น (บาท)</label>
              <input type="number" min={0} step="0.01" value={form.unit_value ?? ''} onChange={set('unit_value')}
                placeholder="เช่น 200 (เว้นว่างได้)"
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
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
  const [showDocs, setShowDocs] = useState(false)
  const [showImport, setShowImport] = useState(false)
  // ช่วงวันที่ default = เดือนนี้ (ต้นเดือน → วันนี้)
  const _today = new Date().toISOString().slice(0, 10)
  const [docRange, setDocRange] = useState({ from: _today.slice(0, 8) + '01', to: _today })

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

  // ปลดระวาง: ถามเหตุผลด้วย prompt (ใช้ออกใบปลดระวาง/ร่างออก ภายหลัง) — ยกเลิกได้ถ้ากด Cancel
  const retire = (id, name) => {
    const reason = window.prompt(`ปลดระวาง "${name}"\nระบุเหตุผล (เช่น ชำรุด/สูญหาย/หมดสภาพ):`, '')
    if (reason === null) return // กด Cancel
    setConfirm({
      title: 'ปลดระวางอุปกรณ์',
      message: `ปลดระวาง "${name}" ?\nเหตุผล: ${reason.trim() || '(ไม่ระบุ)'}\nอุปกรณ์จะไม่สามารถยืมได้อีก`,
      confirmLabel: 'ปลดระวาง',
      danger: true,
      onConfirm: async () => { setConfirm(null); await equipmentApi.retire(id, reason.trim()); load() },
    })
  }

  // ดาวน์โหลด PDF ใบรับเข้าคลัง (receipt) / ใบปลดระวาง (disposal) ตามช่วงวันที่
  const downloadDoc = async (kind) => {
    if (!docRange.from || !docRange.to) { alert('กรุณาเลือกช่วงวันที่'); return }
    try {
      openPdf(await equipmentApi.stockDocument(kind, docRange.from, docRange.to))
    } catch (e) {
      alert(e.response?.data?.detail || 'ไม่สามารถสร้างเอกสารได้')
    }
  }

  const downloadRepairDoc = async () => {
    try {
      openPdf(await equipmentApi.repairDocument())
    } catch (e) {
      alert(e.response?.data?.detail || 'ไม่สามารถสร้างเอกสารได้')
    }
  }

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
          <button onClick={() => setShowDocs((v) => !v)}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            เอกสารคลัง
          </button>
          <button onClick={() => setShowCats(true)}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            จัดการหมวดหมู่
          </button>
          <button onClick={() => setShowImport(true)}
            className="rounded-lg border border-blue-300 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50">
            นำเข้าจากไฟล์ทะเบียน
          </button>
          <button onClick={() => setModal('create')}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
            + เพิ่มอุปกรณ์
          </button>
        </div>
      </div>

      {showDocs && (
        <div className="mb-6 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <h2 className="mb-1 text-sm font-bold text-gray-700">เอกสารคลัง (ร่างเข้า / ร่างออก)</h2>
          <p className="mb-3 text-xs text-gray-500">ออกใบรับเข้าคลัง/ใบปลดระวางเป็น PDF ตามช่วงวันที่ที่นำเข้า/ปลดระวาง</p>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-gray-600">
              จากวันที่
              <input type="date" value={docRange.from}
                onChange={(e) => setDocRange((r) => ({ ...r, from: e.target.value }))}
                className="mt-1 block rounded-lg border border-gray-300 px-3 py-2 text-sm" />
            </label>
            <label className="text-xs text-gray-600">
              ถึงวันที่
              <input type="date" value={docRange.to}
                onChange={(e) => setDocRange((r) => ({ ...r, to: e.target.value }))}
                className="mt-1 block rounded-lg border border-gray-300 px-3 py-2 text-sm" />
            </label>
            <button onClick={() => downloadDoc('receipt')}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
              ใบรับเข้าคลัง (ร่างเข้า)
            </button>
            <button onClick={() => downloadDoc('disposal')}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700">
              ใบปลดระวาง (ร่างออก)
            </button>
          </div>
          <div className="mt-4 border-t border-gray-200 pt-3">
            <p className="mb-2 text-xs text-gray-500">
              บันทึกขออนุมัติซ่อมแซมครุภัณฑ์ — ออกจากครุภัณฑ์ที่สถานะชำรุด/กำลังซ่อมทั้งหมด (ลักษณะที่ชำรุดดึงจากตอนรับคืน)
            </p>
            <button onClick={downloadRepairDoc}
              className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-700">
              ใบขออนุมัติซ่อมแซมครุภัณฑ์
            </button>
          </div>
        </div>
      )}

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
          <option value="material">วัสดุ</option>
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
                      : <div title="ยังไม่มีรูป — ควรเพิ่มรูปให้ครบ"
                             className="w-10 h-10 rounded bg-amber-50 border border-amber-300 flex items-center justify-center text-amber-400">🖼</div>}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-500">{eq.code}</td>
                  <td className="px-4 py-2.5 font-medium text-gray-800">{eq.name}</td>
                  <td className="px-4 py-2.5 text-gray-500 text-xs">{(eq.categories ?? []).map((c) => c.name).join(', ') || '—'}</td>
                  <td className="px-4 py-2.5 text-gray-500">{{ durable: 'ครุภัณฑ์', material: 'วัสดุ', consumable: 'สิ้นเปลือง' }[eq.item_type] ?? eq.item_type}</td>
                  <td className="px-4 py-2.5 text-gray-600">{eq.quantity_available}/{eq.quantity_total} {eq.unit ?? ''}</td>
                  <td className={`px-4 py-2.5 font-medium ${STATUS_STYLE[eq.status] ?? ''}`}>
                    {STATUS_LABEL[eq.status] ?? eq.status}
                    {!eq.is_borrowable && <span className="ml-1 text-xs text-gray-500">· ของประจำห้อง</span>}
                  </td>
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

      {showImport && (
        <ImportModal
          categories={categories}
          onClose={() => setShowImport(false)}
          onDone={() => { setShowImport(false); reloadCategories(); load() }}
        />
      )}
    </div>
  )
}

const IMPORT_ACTION = {
  new: { label: 'เพิ่มใหม่', cls: 'bg-green-50 text-green-700', log: 'เพิ่มอุปกรณ์เข้าคลัง' },
  update: { label: 'อัปเดต', cls: 'bg-blue-50 text-blue-700', log: 'แก้ไขข้อมูลอุปกรณ์' },
  retire: { label: 'เสนอปลดระวาง', cls: 'bg-red-50 text-red-700', log: 'ปลดระวางอุปกรณ์' },
  unchanged: { label: 'ไม่เปลี่ยน', cls: 'bg-gray-50 text-gray-500', log: '—' },
}
const FIELD_LABEL = { name: 'ชื่อ', location: 'สถานที่', status: 'สถานะ', quantity_total: 'จำนวน' }
const IMPORT_STATUS = { available: 'ปกติ', damaged: 'ชำรุด', unavailable: 'สูญหาย/เสื่อมสภาพ', retired: 'ปลดระวาง', borrowed: 'ถูกยืม', under_repair: 'ซ่อม' }
const EDITABLE_STATUS = ['available', 'damaged', 'unavailable']
const ITEM_TYPES = [['durable', 'ครุภัณฑ์'], ['material', 'วัสดุใช้ซ้ำ'], ['consumable', 'วัสดุสิ้นเปลือง']]
const fmtVal = (field, v) => (field === 'status' ? (IMPORT_STATUS[v] ?? v) : (v ?? '—'))

// นำเข้าจากไฟล์ทะเบียน 3 จังหวะ: อัปโหลด → สรุปว่าไฟล์เปลี่ยนอะไร → ร่างเอกสาร (ตรวจ/แก้/ตัดออก) → บันทึกจริง
function ImportModal({ categories, onClose, onDone }) {
  const { user } = useAuthContext()
  const [step, setStep] = useState('upload') // upload | summary | draft
  const [file, setFile] = useState(null)
  const [meta, setMeta] = useState(null)     // { import_id, filename, summary, skipped }
  const [rows, setRows] = useState([])       // ร่างที่แก้ได้
  const [expanded, setExpanded] = useState(null) // code ของแถวที่กางแก้อยู่
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const upload = async () => {
    if (!file) return
    setBusy(true); setError('')
    try {
      const res = await equipmentApi.importPreview(file)
      setMeta(res)
      // retire ไม่ติ๊กมาให้เอง — ถ้าไฟล์เป็นทะเบียนบางส่วน ของที่ยังอยู่จะโดนปลดระวางทั้งดุ้น
      setRows(res.rows.filter((r) => r.action !== 'unchanged').map((r) => ({
        ...r,
        include: r.action !== 'retire',
        quantity: r.quantity_total ?? 1,
        unit: r.unit ?? '',
        // หมวดหมู่: ของใหม่ใช้ที่ระบบเดาจากชื่อ / ของเดิมปล่อยว่าง = ไม่แตะหมวดเดิมใน DB
        categories: r.action === 'new' && r.category ? [r.category] : [],
        description: '',
        image_urls: [],
        reason: '',
      })))
      setStep('summary')
    } catch (err) {
      setError(errMsg(err, 'อ่านไฟล์ไม่สำเร็จ'))
    } finally { setBusy(false) }
  }

  const patch = (code, changes) => setRows((rs) => rs.map((r) => (r.code === code ? { ...r, ...changes } : r)))

  const uploadImages = async (code, files) => {
    if (!files?.length) return
    setBusy(true); setError('')
    try {
      const res = await Promise.all([...files].map((f) => equipmentApi.uploadImage(f)))
      setRows((rs) => rs.map((r) => (r.code === code
        ? { ...r, image_urls: [...r.image_urls, ...res.map((x) => x.image_url)] } : r)))
    } catch (err) {
      setError(errMsg(err, 'อัปโหลดรูปไม่สำเร็จ'))
    } finally { setBusy(false) }
  }

  const selected = rows.filter((r) => r.include)

  const commit = async () => {
    setBusy(true); setError('')
    try {
      const applied = await equipmentApi.importCommit(meta.import_id, {
        filename: meta.filename,
        rows: selected.map((r) => ({
          code: r.code, action: r.action, name: r.name, location: r.location, status: r.status,
          item_type: r.item_type, quantity: Number(r.quantity) || 1, unit: r.unit || null,
          categories: r.categories, description: r.description || null,
          image_urls: r.image_urls, reason: r.reason || null,
        })),
      })
      alert(`บันทึกเข้าระบบแล้ว — เพิ่ม ${applied.new} · แก้ไข ${applied.update} · ปลดระวาง ${applied.retire}\n`
        + 'ออกใบรับเข้าคลัง/ใบปลดระวาง (PDF) ได้จากปุ่ม "เอกสารคลัง"')
      onDone()
    } catch (err) {
      setError(errMsg(err, 'บันทึกไม่สำเร็จ'))
      setBusy(false)
    }
  }

  const s = meta?.summary
  const today = new Date().toLocaleDateString('th-TH', { day: '2-digit', month: 'long', year: 'numeric' })
  const count = (a) => selected.filter((r) => r.action === a).length

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[92vh] w-full max-w-6xl flex-col rounded-xl bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-bold text-gray-800">
            {step === 'draft' ? 'ร่างเอกสารปรับปรุงคลัง — ตรวจก่อนบันทึก' : 'นำเข้าอุปกรณ์จากไฟล์ทะเบียน (Excel / รูปถ่าย / PDF)'}
          </h2>
          <p className="mt-0.5 text-xs text-gray-500">
            {step === 'draft'
              ? 'นี่คือรายการที่จะถูกบันทึกเข้าระบบและลง log — กด “แก้ไข” เพื่อเติมหมวดหมู่ รูป คำอธิบาย ประเภท/จำนวน ได้เหมือนเพิ่มทีละชิ้น'
              : 'ไฟล์ Excel: อ่านชีต “คณะเทคโนฯดิจิทัล”, “ครุภัณฑ์ที่ได้รับพระราชทาน” และ “วัสดุ” · รูปถ่าย/PDF ของทะเบียนวัสดุก็ได้ (โหมดทดลอง — อ่านด้วย OCR ต้องตรวจทุกแถวก่อนบันทึก)'}
          </p>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {error && <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}

          {step === 'upload' && (
            <div className="flex items-center gap-3 py-4">
              <input type="file" accept=".xlsx,.pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="flex-1 text-sm" />
              <button onClick={upload} disabled={!file || busy}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
                {busy ? 'กำลังอ่านไฟล์…' : 'อ่านไฟล์'}
              </button>
            </div>
          )}

          {step === 'summary' && (
            <>
              <div className="mb-4 grid grid-cols-4 gap-2 text-center">
                {[['เพิ่มใหม่', s.new, 'text-green-700'], ['อัปเดต', s.update, 'text-blue-700'],
                  ['ไม่พบในไฟล์', s.retire, 'text-red-700'], ['ไม่เปลี่ยน', s.unchanged, 'text-gray-500']].map(([label, n, cls]) => (
                  <div key={label} className="rounded-lg border border-gray-200 py-2">
                    <p className={`text-xl font-bold ${cls}`}>{n}</p>
                    <p className="text-xs text-gray-500">{label}</p>
                  </div>
                ))}
              </div>

              {meta.skipped.length > 0 && (
                <p className="mb-3 rounded-lg bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
                  ข้าม {meta.skipped.length} รายการที่ไม่มีเลขครุภัณฑ์/รหัสในไฟล์ (ต้องออกเลขก่อนจึงนำเข้าได้)
                </p>
              )}

              <div className="rounded-lg border border-gray-200">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-50 text-left text-gray-500">
                    <tr>{['การกระทำ', 'รหัส', 'ชื่อ', 'รายละเอียดที่เปลี่ยน'].map((h) => (
                      <th key={h} className="px-3 py-2 font-medium">{h}</th>))}</tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {rows.length === 0 && (
                      <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-400">ไฟล์นี้ตรงกับคลังทุกรายการ ไม่มีอะไรต้องเปลี่ยน</td></tr>
                    )}
                    {rows.map((r) => (
                      <tr key={r.code}>
                        <td className="px-3 py-2">
                          <span className={`rounded px-1.5 py-0.5 font-medium ${IMPORT_ACTION[r.action].cls}`}>{IMPORT_ACTION[r.action].label}</span>
                        </td>
                        <td className="px-3 py-2 font-mono text-gray-600">{r.code}</td>
                        <td className="px-3 py-2 text-gray-800">{r.name}</td>
                        <td className="px-3 py-2 text-gray-500">
                          {r.action === 'new' && `สถานะ ${IMPORT_STATUS[r.status] ?? r.status}${r.location ? ` · ${r.location}` : ''}`}
                          {r.action === 'retire' && 'ไม่พบในไฟล์ทะเบียนฉบับนี้'}
                          {r.action === 'update' && Object.entries(r.changes).map(([f, [oldV, newV]]) => (
                            <div key={f}>{FIELD_LABEL[f] ?? f}: <span className="line-through">{fmtVal(f, oldV)}</span> → <span className="text-gray-800">{fmtVal(f, newV)}</span></div>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {step === 'draft' && (
            <div className="rounded-lg border border-gray-300 p-5">
              {/* หัวเอกสาร — เหมือนใบรับเข้าคลังที่จะออกเป็น PDF หลังบันทึก */}
              <div className="mb-4 border-b border-dashed border-gray-300 pb-3 text-center">
                <p className="text-xs text-gray-500">สถาบันเทคโนโลยีจิตรลดา — คณะเทคโนโลยีดิจิทัล</p>
                <p className="text-base font-bold text-gray-800">บันทึกปรับปรุงคลังครุภัณฑ์/วัสดุ (ร่าง)</p>
                <p className="mt-1 text-xs text-gray-500">
                  วันที่ {today} · ผู้ทำรายการ {user?.full_name ?? '—'} · ที่มา: {meta.filename}
                </p>
              </div>

              <table className="w-full text-xs">
                <thead className="border-b border-gray-200 text-left text-gray-500">
                  <tr>
                    {['บันทึก', 'log ที่จะลงระบบ', 'รหัส', 'รายการ', 'ประเภท', 'จำนวน', 'สถานที่', 'สถานะ / เหตุผล', ''].map((h, i) => (
                      <th key={i} className="px-2 py-2 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {rows.map((r) => {
                    const isRetire = r.action === 'retire'
                    const open = expanded === r.code
                    return (
                      <Fragment key={r.code}>
                        <tr className={r.include ? '' : 'opacity-40'}>
                          <td className="px-2 py-2">
                            <input type="checkbox" checked={r.include}
                              onChange={(e) => patch(r.code, { include: e.target.checked })} />
                          </td>
                          <td className="px-2 py-2">
                            <span className={`rounded px-1.5 py-0.5 font-medium ${IMPORT_ACTION[r.action].cls}`}>
                              {IMPORT_ACTION[r.action].log}
                            </span>
                          </td>
                          <td className="px-2 py-2 font-mono text-gray-600">{r.code}</td>
                          <td className="px-2 py-2">
                            {isRetire ? <span className="text-gray-700">{r.name}</span> : (
                              <input value={r.name} disabled={!r.include}
                                onChange={(e) => patch(r.code, { name: e.target.value })}
                                className="w-full min-w-40 rounded border border-gray-200 px-2 py-1" />
                            )}
                          </td>
                          <td className="px-2 py-2">
                            {isRetire ? <span className="text-gray-500">{ITEM_TYPES.find(([v]) => v === r.item_type)?.[1]}</span> : (
                              <select value={r.item_type} disabled={!r.include}
                                onChange={(e) => patch(r.code, { item_type: e.target.value })}
                                className="rounded border border-gray-200 bg-white px-1 py-1">
                                {ITEM_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                              </select>
                            )}
                          </td>
                          <td className="px-2 py-2">
                            {isRetire ? <span className="text-gray-500">{r.quantity}</span> : (
                              <input type="number" min="1" value={r.quantity} disabled={!r.include || r.item_type === 'durable'}
                                onChange={(e) => patch(r.code, { quantity: e.target.value })}
                                className="w-16 rounded border border-gray-200 px-2 py-1 disabled:bg-gray-50" />
                            )}
                          </td>
                          <td className="px-2 py-2">
                            {isRetire ? <span className="text-gray-500">{r.location || '—'}</span> : (
                              <input value={r.location ?? ''} disabled={!r.include}
                                onChange={(e) => patch(r.code, { location: e.target.value || null })}
                                className="w-24 rounded border border-gray-200 px-2 py-1" />
                            )}
                          </td>
                          <td className="px-2 py-2">
                            {isRetire ? (
                              <input value={r.reason} disabled={!r.include}
                                placeholder="เหตุผลปลดระวาง (เช่น จำหน่ายออก)"
                                onChange={(e) => patch(r.code, { reason: e.target.value })}
                                className="w-48 rounded border border-gray-200 px-2 py-1" />
                            ) : (
                              <select value={r.status} disabled={!r.include}
                                onChange={(e) => patch(r.code, { status: e.target.value })}
                                className="rounded border border-gray-200 bg-white px-1 py-1">
                                {EDITABLE_STATUS.map((v) => <option key={v} value={v}>{IMPORT_STATUS[v]}</option>)}
                              </select>
                            )}
                          </td>
                          <td className="px-2 py-2">
                            {!isRetire && (
                              <button onClick={() => setExpanded(open ? null : r.code)} disabled={!r.include}
                                className="text-blue-600 hover:underline disabled:text-gray-300">
                                {open ? 'ปิด ▲' : 'แก้ไข ▾'}
                              </button>
                            )}
                          </td>
                        </tr>

                        {open && (
                          <tr className="bg-gray-50">
                            <td colSpan={9} className="px-4 py-3">
                              <div className="grid grid-cols-3 gap-4">
                                <div>
                                  <p className="mb-1 font-medium text-gray-600">หมวดหมู่</p>
                                  <div className="max-h-28 overflow-y-auto rounded border border-gray-200 bg-white p-2">
                                    {categories.map((c) => (
                                      <label key={c.id} className="flex items-center gap-1.5 py-0.5">
                                        <input type="checkbox" checked={r.categories.includes(c.name)}
                                          onChange={(e) => patch(r.code, {
                                            categories: e.target.checked
                                              ? [...r.categories, c.name]
                                              : r.categories.filter((n) => n !== c.name),
                                          })} />
                                        <span>{c.name}</span>
                                      </label>
                                    ))}
                                  </div>
                                  {r.categories.length === 0 && (
                                    <p className="mt-1 text-gray-400">
                                      {r.action === 'new' ? 'ยังไม่เลือก — จะเข้าหมวด “ไม่ระบุหมวดหมู่”' : 'ไม่เลือก = ใช้หมวดเดิมใน DB'}
                                    </p>
                                  )}
                                </div>

                                <div>
                                  <p className="mb-1 font-medium text-gray-600">คำอธิบาย</p>
                                  <textarea rows={3} value={r.description}
                                    onChange={(e) => patch(r.code, { description: e.target.value })}
                                    placeholder={r.action === 'update' ? 'เว้นว่าง = ไม่แก้คำอธิบายเดิม' : 'รายละเอียดเพิ่มเติม'}
                                    className="w-full rounded border border-gray-200 px-2 py-1" />
                                  {r.item_type !== 'durable' && (
                                    <label className="mt-2 block font-medium text-gray-600">
                                      หน่วยนับ
                                      <input value={r.unit} onChange={(e) => patch(r.code, { unit: e.target.value })}
                                        placeholder="เช่น ม้วน / ชิ้น / เมตร"
                                        className="mt-1 w-full rounded border border-gray-200 px-2 py-1 font-normal" />
                                    </label>
                                  )}
                                </div>

                                <div>
                                  <p className="mb-1 font-medium text-gray-600">รูปภาพ (รูปแรก = ปก)</p>
                                  {r.image_urls.length > 0 && (
                                    <div className="mb-2 flex flex-wrap gap-1">
                                      {r.image_urls.map((url) => (
                                        <div key={url} className="relative">
                                          <img src={imageSrc(url)} alt="" className="h-14 w-14 rounded border border-gray-200 object-cover" />
                                          <button onClick={() => patch(r.code, { image_urls: r.image_urls.filter((u) => u !== url) })}
                                            className="absolute -right-1 -top-1 h-4 w-4 rounded-full bg-red-600 text-[10px] leading-4 text-white">×</button>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                  <input type="file" accept="image/*" multiple
                                    onChange={(e) => uploadImages(r.code, e.target.files)}
                                    className="w-full text-[11px]" />
                                  {r.action === 'update' && <p className="mt-1 text-gray-400">ไม่อัปโหลด = ใช้รูปเดิม</p>}
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>

              <p className="mt-4 border-t border-dashed border-gray-300 pt-3 text-xs text-gray-500">
                จะบันทึกทั้งหมด {selected.length} รายการ — เพิ่ม {count('new')} · แก้ไข {count('update')} · ปลดระวาง {count('retire')}
                <span className="block">ทุกบรรทัดจะถูกลง audit log ในชื่อ {user?.full_name ?? '—'} และนำไปออกใบรับเข้าคลัง/ใบปลดระวาง (PDF) ได้</span>
              </p>
            </div>
          )}
        </div>

        <div className="flex justify-between gap-2 border-t border-gray-200 px-6 py-4">
          <button onClick={step === 'draft' ? () => setStep('summary') : onClose} disabled={busy}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50">
            {step === 'draft' ? '← กลับไปแก้' : 'ปิด'}
          </button>
          {step === 'summary' && (
            <button onClick={() => setStep('draft')} disabled={rows.length === 0}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
              ตรวจร่างเอกสาร →
            </button>
          )}
          {step === 'draft' && (
            <button onClick={commit} disabled={busy || selected.length === 0}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
              {busy ? 'กำลังบันทึก…' : `ยืนยันบันทึกเข้าระบบ (${selected.length})`}
            </button>
          )}
        </div>
      </div>
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
