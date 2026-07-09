import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { equipmentApi } from '../../api/equipmentApi.js'
import { useCart } from '../../context/CartContext.jsx'
import Pagination from '../../components/common/Pagination.jsx'

const STATUS_LABEL = { available: 'พร้อมให้ยืม', borrowed: 'ถูกยืมอยู่', under_repair: 'ซ่อมอยู่', damaged: 'เสียหาย', retired: 'ปลดระวาง', unavailable: 'ไม่อนุญาตให้ยืม' }
const TYPE_LABEL = { durable: 'ครุภัณฑ์', material: 'วัสดุ', consumable: 'วัสดุสิ้นเปลือง' }

export default function EquipmentListPage() {
  const navigate = useNavigate()
  const { cart, addItem } = useCart()
  const [data, setData] = useState({ items: [], total: 0 })
  const [categories, setCategories] = useState([])
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
  }, [])

  useEffect(() => {
    setLoading(true)
    equipmentApi
      .list({ search: search || undefined, category_id: categoryId || undefined, page, page_size: 12 })
      .then(setData)
      .finally(() => setLoading(false))
  }, [search, categoryId, page])

  const isAvailable = (eq) => eq.status === 'available' && eq.quantity_available > 0

  // เหตุผลที่ยืมไม่ได้ — ดู status ก่อน (unavailable/damaged/…), ถ้า available แต่ของหมดค่อยบอกว่ายืมหมด/ของหมด
  const unavailableReason = (eq) =>
    eq.status !== 'available'
      ? (STATUS_LABEL[eq.status] ?? eq.status)
      : (eq.item_type !== 'durable' ? 'หมด' : 'ถูกยืมอยู่')

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">อุปกรณ์ทั้งหมด</h1>
        <button
          onClick={() => navigate('/borrow')}
          className="relative rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
        >
          ตะกร้า
          {cart.length > 0 && (
            <span className="absolute -top-2 -right-2 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
              {cart.length}
            </span>
          )}
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-6">
        <input
          type="text"
          placeholder="ค้นหาชื่ออุปกรณ์…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <select
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">ทุกหมวดหมู่</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
      ) : data.items.length === 0 ? (
        <p className="text-center text-gray-400 py-16">ไม่พบอุปกรณ์</p>
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
                  <Link to={`/equipment/${eq.id}`} className="font-semibold text-gray-800 hover:text-blue-600 leading-tight">
                    {eq.name}
                  </Link>
                  <span className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${
                    available ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                  }`}>
                    {available ? 'พร้อมให้ยืม' : unavailableReason(eq)}
                  </span>
                </div>
                <p className="text-xs text-gray-400">{TYPE_LABEL[eq.item_type]} · {eq.code}</p>
                {available ? (
                  <p className="text-xs text-gray-500">เหลือให้ยืม: {eq.quantity_available} {eq.unit ?? 'ชิ้น'}</p>
                ) : (
                  <p className="text-xs text-red-500">{unavailableReason(eq)} · ยืมไม่ได้ตอนนี้</p>
                )}
                <button
                  disabled={!available || inCart}
                  onClick={() => addItem(eq)}
                  className="mt-auto w-full rounded-lg py-1.5 text-sm font-medium transition-colors
                    disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed
                    enabled:bg-blue-50 enabled:text-blue-600 enabled:hover:bg-blue-100"
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
