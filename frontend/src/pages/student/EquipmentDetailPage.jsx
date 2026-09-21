import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { equipmentApi } from '../../api/equipmentApi.js'
import { bundleApi } from '../../api/bundleApi.js'
import { useCart } from '../../context/CartContext.jsx'
import { useAuthContext } from '../../context/AuthContext.jsx'
import { isStaff } from '../../utils/role.js'
import { formatAge, formatDate, formatMoney } from '../../utils/formatDate.js'
import { STATUS_LABEL } from '../../components/equipment/StatusBadge.jsx'
import EmptyState from '../../components/common/EmptyState.jsx'

const TYPE_LABEL = { durable: 'ครุภัณฑ์', material: 'วัสดุใช้ซ้ำ', consumable: 'วัสดุสิ้นเปลือง' }

const imgSrc = (url) => (url?.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${url}` : url)

export default function EquipmentDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { cart, addItem, addBundle } = useCart()
  const { user } = useAuthContext()
  const isAdmin = isStaff(user)
  const [eq, setEq] = useState(null)
  const [bundles, setBundles] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeImg, setActiveImg] = useState(0)
  // สเปกปัจจุบันจากชิ้นส่วนที่ยังติดตั้งอยู่ (เฟส 8, ข้อ 17) — ผู้ยืมต้องรู้ว่าเครื่องนี้ RAM/SSD เท่าไหร่
  // ก่อนตัดสินใจยืม ไม่ใช่เห็นแค่ชื่อรุ่นแล้วไปลุ้นเอาหน้างาน
  const [parts, setParts] = useState([])

  useEffect(() => {
    equipmentApi.getGrouped(id).then(setEq).catch(() => navigate('/equipment')).finally(() => setLoading(false))
    bundleApi.list().then(setBundles).catch(() => {})
    equipmentApi.listParts(id, false).then(setParts).catch(() => setParts([]))
  }, [id])

  if (loading) return <EmptyState>กำลังโหลด…</EmptyState>
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
                    className={`shrink-0 rounded-lg overflow-hidden border-2 ${i === activeImg ? 'border-primary-500' : 'border-transparent'}`}>
                    <img src={imgSrc(url)} alt="" className="w-14 h-14 object-cover" />
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="p-6 space-y-4">
          <div className="flex items-start justify-between gap-4">
            <h1 className="text-xl font-light text-gray-800">{eq.name}</h1>
            <span className={`shrink-0 text-sm px-3 py-1 rounded-full font-medium ${
              available ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
            }`}>
              {available ? 'พร้อมให้ยืม' : reason}
            </span>
          </div>

          <table className="w-full text-sm text-gray-600">
            <tbody className="divide-y divide-gray-100">
              {[
                // ซ่อนรหัสหน่วยเจาะจงถ้ามีมากกว่า 1 หน่วย — spread แบบมีเงื่อนไข เพราะ ['label', undefined] ไม่ falsy
                ...(eq.unit_count === 1 ? [['รหัสอุปกรณ์', eq.code]] : []),
                ['ประเภท', TYPE_LABEL[eq.item_type]],
                // รุ่น/ผู้ผลิต — คนที่รู้จักแต่ชื่อรุ่น ("DHT11") ต้องยืนยันได้ว่าใช่ตัวที่ตามหา
                ...(eq.model_number ? [['รุ่น', eq.model_number]] : []),
                ...(eq.manufacturer ? [['ผู้ผลิต', eq.manufacturer]] : []),
                ['หมวดหมู่', (eq.categories ?? []).map((c) => c.name).join(', ') || '—'],
                ['ที่เก็บ', eq.location ?? '—'],
                ['เหลือให้ยืม', `${eq.quantity_available} ${eq.unit ?? 'ชิ้น'}`],
                // นักศึกษาเห็นอายุได้ (ช่วยตัดสินใจว่าจะยืมรุ่นไหน) แต่ไม่ต้องเห็นราคา/มูลค่าทางบัญชี — แอดมินเห็นครบ
                ...(eq.acquired_at ? [['อายุการใช้งาน', `${formatAge(eq.acquired_at)} (ได้มา ${formatDate(eq.acquired_at)})`]] : []),
                ...(isAdmin && eq.unit_value != null
                  ? [['มูลค่า', `แท้จริง ${formatMoney(eq.unit_value)} / ตามบัญชี ${formatMoney(eq.book_value)} บ.`]]
                  : []),
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
                    <span className="text-gray-400">{h.due_date ? `กำหนดคืน ${formatDate(h.due_date)}` : ''}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {parts.length > 0 && (
            <div className="border-t pt-4">
              <p className="text-sm font-medium text-gray-500 mb-2">สเปกปัจจุบัน (ชิ้นส่วนที่ติดตั้งอยู่)</p>
              <ul className="space-y-1 text-sm text-gray-600">
                {parts.map((p) => (
                  <li key={p.id} className="flex justify-between gap-3">
                    <span>{p.name}</span>
                    <span className="text-gray-400 text-xs shrink-0">
                      ติดตั้ง {formatDate(p.acquired_at)}
                      {p.replaces_part_name ? ` · แทน ${p.replaces_part_name}` : ''}
                    </span>
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
            className="w-full rounded-full py-2.5 text-sm font-semibold transition-colors
              disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed
              enabled:bg-primary-600 enabled:text-white enabled:hover:bg-primary-700"
          >
            {inCart ? 'อยู่ในตะกร้าแล้ว' : available ? 'เพิ่มในตะกร้าและยื่นคำขอ' : 'ไม่พร้อมให้ยืม'}
          </button>
        </div>
      </div>
    </div>
  )
}
