import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { equipmentApi } from '../../api/equipmentApi.js'
import { useCart } from '../../context/CartContext.jsx'

const STATUS_LABEL = { available: 'พร้อมให้ยืม', borrowed: 'ถูกยืมอยู่', under_repair: 'ซ่อมอยู่', damaged: 'เสียหาย', retired: 'ปลดระวาง' }
const TYPE_LABEL = { durable: 'ครุภัณฑ์', consumable: 'วัสดุสิ้นเปลือง' }

export default function EquipmentDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { cart, addItem } = useCart()
  const [eq, setEq] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    equipmentApi.get(id).then(setEq).catch(() => navigate('/equipment')).finally(() => setLoading(false))
  }, [id])

  if (loading) return <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>
  if (!eq) return null

  const inCart = cart.some((c) => c.equipment.id === eq.id)
  const available = eq.quantity_available > 0 && (eq.item_type === 'consumable' || eq.status === 'available')

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <button onClick={() => navigate('/equipment')} className="text-sm text-gray-400 hover:text-gray-600 mb-6 flex items-center gap-1">
        ← กลับ
      </button>

      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
        {eq.image_url && (
          <img src={eq.image_url.startsWith('/') ? `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}${eq.image_url}` : eq.image_url} alt={eq.name} className="w-full h-56 object-cover" />
        )}
        <div className="p-6 space-y-4">
          <div className="flex items-start justify-between gap-4">
            <h1 className="text-xl font-bold text-gray-800">{eq.name}</h1>
            <span className={`shrink-0 text-sm px-3 py-1 rounded-full font-medium ${
              available ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
            }`}>
              {STATUS_LABEL[eq.status] ?? eq.status}
            </span>
          </div>

          <table className="w-full text-sm text-gray-600">
            <tbody className="divide-y divide-gray-100">
              {[
                ['รหัสอุปกรณ์', eq.code],
                ['ประเภท', TYPE_LABEL[eq.item_type]],
                ['ที่เก็บ', eq.location ?? '—'],
                eq.item_type === 'consumable' && ['คงเหลือ', `${eq.quantity_available} ${eq.unit ?? 'ชิ้น'}`],
              ].filter(Boolean).map(([label, val]) => (
                <tr key={label}>
                  <td className="py-2 pr-4 font-medium text-gray-500 w-28">{label}</td>
                  <td className="py-2">{val}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {eq.description && (
            <p className="text-sm text-gray-600 border-t pt-4">{eq.description}</p>
          )}

          <button
            disabled={!available || inCart}
            onClick={() => { addItem(eq); navigate('/borrow') }}
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
