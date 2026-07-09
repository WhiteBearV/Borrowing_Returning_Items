import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { borrowApi } from '../../api/borrowApi.js'
import { useCart } from '../../context/CartContext.jsx'

export default function BorrowRequestPage() {
  const navigate = useNavigate()
  const { cart, removeItem, updateQuantity, clearCart } = useCart()
  const [purpose, setPurpose] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const cartPayload = () => ({
    purpose: purpose || undefined,
    items: cart.map((c) => ({ equipment_id: c.equipment.id, quantity: c.quantity })),
  })

  const previewDraft = async () => {
    setError('')
    try {
      const blob = await borrowApi.previewPdf(cartPayload())
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank')
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (err) {
      setError(err.response?.data?.detail ?? 'สร้างตัวอย่างไม่สำเร็จ')
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (cart.length === 0) return
    setError('')
    setLoading(true)
    try {
      await borrowApi.create(cartPayload())
      clearCart()
      navigate('/my-borrows')
    } catch (err) {
      setError(err.response?.data?.detail ?? 'ยื่นคำขอไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }

  if (cart.length === 0) {
    return (
      <div className="max-w-lg mx-auto px-4 py-16 text-center">
        <p className="text-gray-400 mb-4">ตะกร้าว่างเปล่า</p>
        <Link to="/equipment" className="text-blue-600 hover:underline text-sm font-medium">
          ← เลือกอุปกรณ์
        </Link>
      </div>
    )
  }

  return (
    <div className="max-w-lg mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">ยื่นคำขอยืมอุปกรณ์</h1>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Cart items */}
        <div className="bg-white rounded-xl border border-gray-200 divide-y">
          {cart.map(({ equipment: eq, quantity }) => (
            <div key={eq.id} className="flex items-center gap-3 p-4">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800 truncate">{eq.name}</p>
                <p className="text-xs text-gray-400">{eq.code}</p>
              </div>
              {eq.item_type !== 'durable' ? (
                <input
                  type="number"
                  min={1}
                  max={eq.quantity_available}
                  value={quantity}
                  onChange={(e) => updateQuantity(eq.id, Number(e.target.value))}
                  className="w-16 rounded border border-gray-300 px-2 py-1 text-sm text-center"
                />
              ) : (
                <span className="text-sm text-gray-500">1 ชิ้น</span>
              )}
              <button
                type="button"
                onClick={() => removeItem(eq.id)}
                className="text-gray-300 hover:text-red-500 text-lg leading-none"
              >
                ×
              </button>
            </div>
          ))}
        </div>

        {/* Purpose */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">วัตถุประสงค์การยืม</label>
          <textarea
            rows={3}
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            placeholder="ระบุวัตถุประสงค์ (ไม่บังคับ)"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        <div className="flex gap-3">
          <Link
            to="/equipment"
            className="flex-1 text-center rounded-lg border border-gray-300 py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            + เพิ่มอุปกรณ์
          </Link>
          <button
            type="button"
            onClick={previewDraft}
            className="flex-1 rounded-lg border border-blue-300 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50"
          >
            ดูตัวอย่างใบยืม
          </button>
          <button
            type="submit"
            disabled={loading}
            className="flex-1 rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'กำลังส่ง…' : 'ยื่นคำขอ'}
          </button>
        </div>
      </form>
    </div>
  )
}
