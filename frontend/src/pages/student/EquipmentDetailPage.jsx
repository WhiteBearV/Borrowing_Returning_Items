import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { equipmentApi } from '../../api/equipmentApi.js'
import { bundleApi } from '../../api/bundleApi.js'
import { useCart } from '../../context/CartContext.jsx'

const STATUS_LABEL = { available: 'พร้อมให้ยืม', borrowed: 'ถูกยืมอยู่', under_repair: 'ซ่อมอยู่', damaged: 'เสียหาย', retired: 'ปลดระวาง', unavailable: 'ไม่อนุญาตให้ยืม' }
const TYPE_LABEL = { durable: 'ครุภัณฑ์', material: 'วัสดุ', consumable: 'วัสดุสิ้นเปลือง' }

const imgSrc = (url) => (url?.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${url}` : url)

export default function EquipmentDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { cart, addItem, addBundle } = useCart()
  const [eq, setEq] = useState(null)
  const [bundles, setBundles] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeImg, setActiveImg] = useState(0)

  useEffect(() => {
    equipmentApi.get(id).then(setEq).catch(() => navigate('/equipment')).finally(() => setLoading(false))
    bundleApi.list().then(setBundles).catch(() => {})
  }, [id])

  if (loading) return <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
  if (!eq) return null

  const images = eq.image_urls?.length ? eq.image_urls : (eq.image_url ? [eq.image_url] : [])
  const inCart = cart.some((c) => c.equipment.id === eq.id)
  const available = eq.is_borrowable && eq.status === 'available' && eq.quantity_available > 0
  // เหตุผลที่ยืมไม่ได้ — ของประจำห้องมาก่อน แล้วดู status ถ้า available แต่ของหมดค่อยบอกว่ายืมหมด/ของหมด
  const reason = !eq.is_borrowable
    ? 'ของประจำห้อง (ไม่ให้ยืมออก)'
    : eq.status !== 'available'
      ? (STATUS_LABEL[eq.status] ?? eq.status)
      : (eq.item_type !== 'durable' ? 'หมด' : 'ถูกยืมอยู่')

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <button onClick={() => navigate(-1)} className="text-sm text-gray-400 hover:text-gray-600 mb-6 flex items-center gap-1">
        ← กลับ
      </button>

      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
        {images.length > 0 && (
          <div>
            <div className="relative bg-gray-50">
              <img src={imgSrc(images[activeImg] ?? images[0])} alt={eq.name} className="w-full h-72 object-contain" />
              {images.length > 1 && (
                <>
                  <button type="button" aria-label="รูปก่อนหน้า"
                    onClick={() => setActiveImg((i) => (i - 1 + images.length) % images.length)}
                    className="absolute left-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full bg-white/80 shadow flex items-center justify-center text-gray-600 hover:bg-white">
                    ‹
                  </button>
                  <button type="button" aria-label="รูปถัดไป"
                    onClick={() => setActiveImg((i) => (i + 1) % images.length)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full bg-white/80 shadow flex items-center justify-center text-gray-600 hover:bg-white">
                    ›
                  </button>
                  <span className="absolute bottom-2 right-3 text-xs bg-black/50 text-white rounded-full px-2 py-0.5">
                    {activeImg + 1}/{images.length}
                  </span>
                </>
              )}
            </div>
            {images.length > 1 && (
              <div className="flex gap-2 p-3 overflow-x-auto">
                {images.map((url, i) => (
                  <button key={url} type="button" onClick={() => setActiveImg(i)}
                    className={`shrink-0 rounded-lg overflow-hidden border-2 ${i === activeImg ? 'border-blue-500' : 'border-transparent'}`}>
                    <img src={imgSrc(url)} alt="" className="w-14 h-14 object-cover" />
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="p-6 space-y-4">
          <div className="flex items-start justify-between gap-4">
            <h1 className="text-xl font-bold text-gray-800">{eq.name}</h1>
            <span className={`shrink-0 text-sm px-3 py-1 rounded-full font-medium ${
              available ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
            }`}>
              {available ? 'พร้อมให้ยืม' : reason}
            </span>
          </div>

          <table className="w-full text-sm text-gray-600">
            <tbody className="divide-y divide-gray-100">
              {[
                ['รหัสอุปกรณ์', eq.code],
                ['ประเภท', TYPE_LABEL[eq.item_type]],
                ['หมวดหมู่', (eq.categories ?? []).map((c) => c.name).join(', ') || '—'],
                ['ที่เก็บ', eq.location ?? '—'],
                ['เหลือให้ยืม', `${eq.quantity_available} ${eq.unit ?? 'ชิ้น'}`],
              ].filter(Boolean).map(([label, val]) => (
                <tr key={label}>
                  <td className="py-2 pr-4 font-medium text-gray-500 w-28">{label}</td>
                  <td className="py-2">{val}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {eq.holders?.length > 0 && (
            <div className="border-t pt-4">
              <p className="text-sm font-medium text-gray-500 mb-2">ผู้ครอบครองในขณะนี้</p>
              <ul className="space-y-1 text-sm text-gray-600">
                {eq.holders.map((h, i) => (
                  <li key={i} className="flex justify-between">
                    <span>{h.holder_name}{h.quantity > 1 ? ` ×${h.quantity}` : ''}</span>
                    <span className="text-gray-400">{h.due_date ? `กำหนดคืน ${h.due_date}` : ''}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {eq.description && (
            <p className="text-sm text-gray-600 border-t pt-4">{eq.description}</p>
          )}

          {!available && (
            <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-600">
              {reason} · ยืมไม่ได้ตอนนี้
            </div>
          )}

          <button
            disabled={!available || inCart}
            onClick={() => {
              // เป็นตัวกระตุ้นของชุด → เพิ่มยูนิตนี้ + อุปกรณ์ต่อพ่วงในชุด (จับคู่ตามชื่อรุ่นด้วย ครอบทุกยูนิต)
              const bundle = bundles.find(
                (b) => b.trigger_equipment_id === eq.id || (b.trigger_equipment_name && b.trigger_equipment_name === eq.name),
              )
              addItem(eq)
              if (bundle) addBundle(bundle)
              navigate('/borrow')
            }}
            className="w-full rounded-xl py-2.5 text-sm font-semibold transition-colors
              disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed
              enabled:bg-blue-600 enabled:text-white enabled:hover:bg-blue-700"
          >
            {inCart ? 'อยู่ในตะกร้าแล้ว' : available ? 'เพิ่มในตะกร้าและยื่นคำขอ' : 'ไม่พร้อมให้ยืม'}
          </button>
        </div>
      </div>
    </div>
  )
}
