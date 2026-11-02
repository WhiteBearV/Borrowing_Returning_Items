import { useAuthContext } from '../../context/AuthContext.jsx'
import { isStaff } from '../../utils/role.js'
import { fineMoney } from '../../utils/fine.js'

/** แจ้งผู้ยืมว่าถูกระงับการยืมเพราะค่าปรับค้างถึงเกณฑ์ (backend บล็อกจริงที่ create_request — ที่นี่แค่บอก)
 *  ค่ามาจาก /users/me (fine_blocked) ซึ่งโหลดตอนเปิดหน้า ชำระแล้วรีเฟรชหน้าก็หาย */
export default function FineBlockBanner() {
  const { user } = useAuthContext()
  if (!user?.fine_blocked || isStaff(user)) return null
  return (
    <div role="alert" className="mb-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <p className="font-semibold">บัญชีของคุณถูกระงับการยืมชั่วคราว</p>
      <p className="mt-1">
        มีค่าปรับค้างชำระ {fineMoney(user.unpaid_fine_total)} บาท (ถึงเกณฑ์ {fineMoney(user.fine_block_threshold)} บาท)
        กรุณาไปพบเจ้าหน้าที่เพื่อชำระค่าปรับหรือขอยกเว้นค่าปรับ จึงจะยืมอุปกรณ์ได้อีกครั้ง
      </p>
    </div>
  )
}
