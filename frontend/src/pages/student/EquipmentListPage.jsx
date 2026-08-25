import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { equipmentApi } from '../../api/equipmentApi.js'
import { bundleApi } from '../../api/bundleApi.js'
import { useCart } from '../../context/CartContext.jsx'
import Pagination from '../../components/common/Pagination.jsx'
import { STATUS_LABEL } from '../../components/equipment/StatusBadge.jsx'
import EmptyState from '../../components/common/EmptyState.jsx'

const TYPE_LABEL = { durable: 'ครุภัณฑ์', material: 'วัสดุ', consumable: 'วัสดุสิ้นเปลือง' }

export default function EquipmentListPage() {
  const navigate = useNavigate()
  const { cart, addItem, addBundle } = useCart()
  const [data, setData] = useState({ items: [], total: 0 })
  const [categories, setCategories] = useState([])
  const [bundles, setBundles] = useState([])
  const [bundleMsg, setBundleMsg] = useState('')
  const [loading, setLoading] = useState(true)

  // เก็บ filter ไว้ใน URL เพื่อให้กดย้อนกลับจากหน้ารายละเอียดแล้วหมวด/หน้าเดิมยังอยู่
  const [params, setParams] = useSearchParams()
  const search = params.get('q') ?? ''
  const categoryId = params.get('cat') ?? ''
  const page = Number(params.get('page') || 1)
  const patch = (obj) => setParams((prev) => {
    const p = new URLSearchParams(prev)
    for (const [k, v] of Object.entries(obj)) v ? p.set(k, v) : p.delete(k)
    return p
  }, { replace: true })
  const setSearch = (v) => patch({ q: v, page: '' })
  const setCategoryId = (v) => patch({ cat: v, page: '' })
  const setPage = (v) => patch({ page: v > 1 ? String(v) : '' })

  const cartIds = new Set(cart.map((c) => c.equipment.id))

  useEffect(() => {
    equipmentApi.listCategories().then(setCategories).catch(() => {})
    bundleApi.list().then(setBundles).catch(() => {})
  }, [])

  const handleAddBundle = (b) => {
    const skipped = addBundle(b)
    setBundleMsg(skipped.length
      ? `เพิ่ม "${b.name}" ลงตะกร้าแล้ว — ยกเว้น ${skipped.join(', ')} (ยืมไม่ได้ตอนนี้)`
      : `เพิ่ม "${b.name}" ลงตะกร้าแล้ว`)
  }

  // อุปกรณ์ที่เป็นตัวกระตุ้นของชุด → กดเพิ่มแล้วขยายเป็นทั้งชุดแทนการเพิ่มชิ้นเดียว
  // จับคู่ตามชื่อรุ่นด้วย เพื่อครอบทุกยูนิตที่ชื่อเดียวกัน (คอมตั้งโต๊ะ 40 เครื่องใช้ชุดเดียว)
  const bundleFor = (eq) => bundles.find(
    (b) => b.trigger_equipment_id === eq.id || (b.trigger_equipment_name && b.trigger_equipment_name === eq.name),
  )
  const handleAdd = (eq) => {
    const bundle = bundleFor(eq)
    if (bundle) {
      addItem(eq)                     // ยูนิตที่กดจริง (เช่น คอม 0006) — ชุดเก็บแค่อุปกรณ์ต่อพ่วง
      return handleAddBundle(bundle)  // + เมาส์/คีย์บอร์ด/สายไฟ ในชุด
    }
    addItem(eq)
  }

  useEffect(() => {
    setLoading(true)
    equipmentApi
      .listGrouped({ search: search || undefined, category_id: categoryId || undefined, page, page_size: 12 })
      .then(setData)
      .finally(() => setLoading(false))
  }, [search, categoryId, page])

  const isAvailable = (eq) => eq.is_borrowable && eq.status === 'available' && eq.quantity_available > 0

  // เหตุผลที่ยืมไม่ได้ — ของประจำห้องมาก่อน แล้วดู status (unavailable/damaged/…), สุดท้ายค่อยบอกว่ายืมหมด/ของหมด
  const unavailableReason = (eq) =>
    !eq.is_borrowable
      ? 'ของประจำห้อง'
      : eq.status !== 'available'
        ? (STATUS_LABEL[eq.status] ?? eq.status)
        : (eq.item_type !== 'durable' ? 'หมด' : 'ถูกยืมอยู่')

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-light text-gray-800">อุปกรณ์ทั้งหมด</h1>
        <button
          onClick={() => navigate('/borrow')}
          className="relative rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700"
        >
          ตะกร้า
          {cart.length > 0 && (
            <span className="absolute -top-2 -right-2 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
              {cart.length}
            </span>
          )}
        </button>
      </div>

      {/* ชุดอุปกรณ์ขยายอัตโนมัติตอนกด "+ เพิ่มในตะกร้า" บนอุปกรณ์ตัวกระตุ้น (ดู handleAdd) — ข้อความผลลัพธ์ */}
      {bundleMsg && (
        <p className="mb-4 rounded-lg bg-primary-50 border border-primary-100 px-3 py-2 text-xs text-gray-600">{bundleMsg}</p>
      )}

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <input
          type="text"
          placeholder="ค้นหาชื่อหรือรหัสอุปกรณ์…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 min-w-0 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
        />
        <select
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
          className="w-full sm:w-48 shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500"
        >
          <option value="">ทุกหมวดหมู่</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <EmptyState>กำลังโหลด…</EmptyState>
      ) : data.items.length === 0 ? (
        <EmptyState>ไม่พบอุปกรณ์</EmptyState>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.items.map((eq) => {
            const available = isAvailable(eq)
            const inCart = cartIds.has(eq.id)
            return (
              <div key={eq.id} className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 flex flex-col gap-2">
                {eq.image_url && (
                  <img src={eq.image_url.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${eq.image_url}` : eq.image_url} alt={eq.name} className="w-full h-36 object-contain rounded-lg mb-1 bg-gray-50" />
                )}
                <div className="flex items-start justify-between gap-2">
                  <Link to={`/equipment/${eq.id}`} className="font-semibold text-gray-800 hover:text-primary-600 leading-tight">
                    {eq.name}
                  </Link>
                  <span className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${
                    available ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                  }`}>
                    {available ? 'พร้อมให้ยืม' : unavailableReason(eq)}
                  </span>
                </div>
                {/* ซ่อนรหัสหน่วยเจาะจงถ้ามีมากกว่า 1 หน่วย — ระบบยังไม่การันตีว่าจะได้หน่วยรหัสนี้จริงตอนอนุมัติ */}
                <p className="text-xs text-gray-400">{TYPE_LABEL[eq.item_type]}{eq.unit_count === 1 ? ` · ${eq.code}` : ''}</p>
                {available ? (
                  <p className="text-xs text-gray-500">เหลือให้ยืม: {eq.quantity_available} {eq.unit ?? 'ชิ้น'}</p>
                ) : (
                  <p className="text-xs text-red-500">{unavailableReason(eq)} · ยืมไม่ได้ตอนนี้</p>
                )}
                <button
                  disabled={!available || inCart}
                  onClick={() => handleAdd(eq)}
                  className="mt-auto w-full rounded-lg py-1.5 text-sm font-medium transition-colors
                    disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed
                    enabled:bg-primary-50 enabled:text-primary-600 enabled:hover:bg-primary-100"
                >
                  {inCart ? 'อยู่ในตะกร้าแล้ว' : available ? '+ เพิ่มในตะกร้า' : 'ไม่พร้อมให้ยืม'}
                </button>
              </div>
            )
          })}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={12} onChange={setPage} />
    </div>
  )
}
