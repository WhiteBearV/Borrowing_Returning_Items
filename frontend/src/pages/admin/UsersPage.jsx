import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { usersApi } from '../../api/usersApi.js'
import ConfirmModal from '../../components/common/ConfirmModal.jsx'
import Pagination from '../../components/common/Pagination.jsx'
import EmptyState from '../../components/common/EmptyState.jsx'
import { ADMIN, STUDENT, SUPERADMIN, isSuperadmin, roleBadgeClass, roleLabel } from '../../utils/role.js'
import { useAuthContext } from '../../context/AuthContext.jsx'

const MAJOR_LABEL = { comp_eng: 'วิศวกรรมคอมพิวเตอร์', digital_design: 'ออกแบบดิจิทัล' }
// ดร. เพิ่มจาก RegisterPage.jsx เพราะ admin สร้างบัญชีอาจารย์ได้ด้วย ไม่ใช่แค่นักศึกษา
const TITLES = ['นาย', 'นาง', 'นางสาว', 'ดร.']

// FastAPI 422 คืน detail เป็น array ของ object — เซ็ตตรง ๆ ลง error state แล้ว render {error} จะ crash
// (pattern เดียวกับ EquipmentManagePage.jsx errMsg — แก้ตามรีวิวรอบ 3, MINOR-4)
const errMsg = (err, fallback) => {
  const d = err.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((e) => e.msg).join(', ')
  return fallback
}

export default function UsersPage() {
  const { user: me } = useAuthContext()
  // เปลี่ยนสิทธิ์/ลบบัญชีเป็นของผู้ดูแลระบบสูงสุด (backend กันด้วย require_superadmin อยู่แล้ว)
  // ซ่อนปุ่มด้วยเพื่อไม่ให้ผู้ดูแลคลังกดแล้วเจอ 403 โดยไม่รู้สาเหตุ
  const canManageRoles = isSuperadmin(me)
  const [data, setData] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [roleFilter, setRoleFilter] = useState('')
  // ชั้นปี (เฟส 10) — "1".."4" / "retained" (ตกค้าง) / "staff" (บุคลากร) คำนวณสดฝั่ง backend
  // (แก้ตามรีวิวรอบ 4, M-j — คอมเมนต์เดิมค้าง "1".."10" จากก่อนจำกัดช่วง study_years)
  // อ่านค่าเริ่มต้นจาก URL (?year_group=) ตอน mount — Dashboard การ์ดชั้นปีลิงก์มาที่นี่พร้อมตัวกรองแล้ว
  // เดิมไม่อ่านเลย ทำให้ลิงก์จาก Dashboard พาเข้ามาหน้านี้แล้วตัวกรองไม่ติดมาด้วย (พบตอนรีวิวรอบ 2)
  const [searchParams] = useSearchParams()
  const [yearFilter, setYearFilter] = useState(searchParams.get('year_group') || '')
  // คิวผู้สมัครที่ระบบตรวจแล้วไม่ตรงรายชื่อของสาขา (เฟส 9) — โหลดแยกจากตารางหลัก
  // เพื่อให้ขึ้นเด่นด้านบนเสมอ ไม่ว่าแอดมินจะกรองอะไรอยู่หรือหน้าไหน
  const [pending, setPending] = useState([])
  const [loading, setLoading] = useState(true)
  const [confirm, setConfirm] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [studyTarget, setStudyTarget] = useState(null)  // ผู้ใช้ที่กำลังแก้ชั้นปี

  const load = () => {
    setLoading(true)
    usersApi.list({ role: roleFilter || undefined, year_group: yearFilter || undefined, page, page_size: 20 })
      .then(setData).finally(() => setLoading(false))
    usersApi.list({ approval_status: 'pending', page: 1, page_size: 50 })
      .then((d) => setPending(d.items)).catch(() => setPending([]))
  }

  const decideApproval = (user, approve) => setConfirm({
    title: approve ? 'อนุมัติผู้สมัคร' : 'ปฏิเสธผู้สมัคร',
    message: approve
      ? `อนุมัติให้ "${user.full_name}" (${user.student_id ?? '—'}) ใช้งานระบบได้?\n`
        + `เหตุผลที่ระบบกันไว้: ${user.approval_note ?? '—'}`
      : `ปฏิเสธคำขอสมัครของ "${user.full_name}" (${user.student_id ?? '—'})?\n`
        + 'บัญชีจะยังอยู่ในระบบแต่เข้าใช้งานไม่ได้ (ลบถาวรทำได้ทีหลัง)',
    confirmLabel: approve ? 'อนุมัติ' : 'ปฏิเสธ',
    danger: !approve,
    onConfirm: async () => {
      setConfirm(null)
      try { await usersApi.updateApproval(user.id, approve); load() }
      catch (e) { alert(e.response?.data?.detail ?? 'บันทึกไม่สำเร็จ') }
    },
  })

  useEffect(() => { load() }, [roleFilter, yearFilter, page])

  const toggleStatus = (user) => {
    const label = user.is_active ? 'ปิดการใช้งาน' : 'เปิดการใช้งาน'
    setConfirm({
      title: `${label}บัญชี`,
      message: `${label} "${user.full_name}" ?`,
      confirmLabel: label,
      danger: user.is_active,
      onConfirm: async () => { setConfirm(null); await usersApi.updateStatus(user.id, !user.is_active); load() },
    })
  }

  const changeRole = (user, role) => {
    if (role === user.role) return
    setConfirm({
      title: 'เปลี่ยนระดับสิทธิ์',
      message: `เปลี่ยนสิทธิ์ของ "${user.full_name}" เป็น "${roleLabel(role)}" ?`,
      confirmLabel: 'เปลี่ยนสิทธิ์',
      danger: role === SUPERADMIN,
      onConfirm: async () => {
        setConfirm(null)
        try { await usersApi.updateRole(user.id, role); load() }
        catch (e) { alert(e.response?.data?.detail ?? 'เปลี่ยนสิทธิ์ไม่สำเร็จ') }
      },
    })
  }

  const deleteUser = (user) => setConfirm({
    title: 'ลบบัญชีถาวร',
    message: `ลบบัญชี "${user.full_name}" ออกจากระบบถาวร?\nประวัติการยืมทั้งหมดจะถูกลบด้วย`,
    confirmLabel: 'ลบถาวร',
    danger: true,
    onConfirm: async () => {
      setConfirm(null)
      try { await usersApi.deleteUser(user.id); load() }
      catch (e) { alert(e.response?.data?.detail ?? 'ลบไม่สำเร็จ') }
    },
  })

  return (
    <div className="px-6 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-light text-gray-800">จัดการผู้ใช้</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            ทั้งหมด {data.total.toLocaleString('th-TH')} บัญชี{roleFilter ? ' (ตามตัวกรองปัจจุบัน)' : ''}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value); setPage(1) }}
            className="flex-1 sm:flex-none rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
            <option value="">ทุกสิทธิ์</option>
            <option value="student">ผู้ใช้งาน (นักศึกษา)</option>
            <option value="admin">ผู้ดูแลคลัง</option>
            <option value="superadmin">ผู้ดูแลระบบสูงสุด</option>
          </select>
          {/* ชั้นปี (เฟส 10) — คำนวณสดจากรหัสนักศึกษา ไม่ใช่คอลัมน์ตรง ให้ backend กรองให้ */}
          <select value={yearFilter} onChange={(e) => { setYearFilter(e.target.value); setPage(1) }}
            className="flex-1 sm:flex-none rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
            <option value="">ทุกชั้นปี</option>
            {[1, 2, 3, 4].map((y) => <option key={y} value={y}>ปี {y}</option>)}
            <option value="retained">ตกค้าง</option>
            <option value="staff">บุคลากร</option>
            {/* Dashboard การ์ดชั้นปีลิงก์มาด้วย ?year_group=unknown ได้ (นักศึกษาที่ enrollment_year เป็น
                None — รหัสไม่ตรงรูปแบบ/ข้อมูลเก่า) เดิม select นี้ไม่มีตัวเลือกนี้ ทำให้โชว์ "ทุกชั้นปี"
                หลอก ๆ ทั้งที่ตัวกรองยังติดอยู่จริง (แก้ตามรีวิวรอบ 3, MINOR-3) */}
            <option value="unknown">ไม่ทราบชั้นปี</option>
          </select>
          <button onClick={() => setShowAdd(true)}
            className="rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700">
            + เพิ่มผู้ใช้
          </button>
        </div>
      </div>

      {pending.length > 0 && (
        <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-sm font-medium text-amber-900">
            ผู้สมัครรออนุมัติ {pending.length} คน
            <span className="font-normal text-amber-700"> — ไม่พบชื่อ/รหัสในรายชื่อที่สาขารับรอง</span>
          </p>
          <ul className="mt-2 divide-y divide-amber-200/70">
            {pending.map((u) => (
              <li key={u.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
                <span className="font-medium text-gray-800">{u.full_name}</span>
                <span className="font-mono text-xs text-gray-500">{u.student_id ?? u.username ?? '—'}</span>
                <span className="text-xs text-gray-500">{u.email}</span>
                <span className="text-xs text-amber-700 flex-1 min-w-[12rem]">{u.approval_note}</span>
                <button onClick={() => decideApproval(u, true)}
                  className="text-xs font-medium text-emerald-700 hover:underline">อนุมัติ</button>
                <button onClick={() => decideApproval(u, false)}
                  className="text-xs text-red-600 hover:underline">ปฏิเสธ</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {loading ? (
        <EmptyState>กำลังโหลด…</EmptyState>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['ชื่อ', 'อีเมล', 'รหัสประจำตัว', 'สาขา', 'ชั้นปี', 'สถานะ', ''].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((u) => (
                <tr key={u.id} className={`hover:bg-gray-50 ${!u.is_active ? 'opacity-50' : ''}`}>
                  <td className="px-4 py-2.5 font-medium text-gray-800">
                    {u.full_name}
                    {/* ป้ายสิทธิ์ใช้ชุดเดียวกับแถบบน/เมนู (utils/role.js) — เดิมเขียนคำว่า "admin" ดิบไว้ตรงนี้ */}
                    {u.role !== 'student' && (
                      <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${roleBadgeClass(u.role)}`}>{roleLabel(u.role)}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-gray-500">{u.email}</td>
                  <td className="px-4 py-2.5 text-gray-500 font-mono text-xs">{u.student_id ?? u.username ?? '—'}</td>
                  <td className="px-4 py-2.5 text-gray-500 text-xs">{MAJOR_LABEL[u.major] ?? '—'}</td>
                  <td className="px-4 py-2.5 text-xs">
                    <span className={u.is_retained ? 'text-amber-600 font-medium' : 'text-gray-500'}>
                      {u.study_year_label}
                    </span>
                    {u.student_id && (
                      <button onClick={() => setStudyTarget(u)} className="ml-1.5 text-primary-600 hover:underline">แก้</button>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    {u.approval_status === 'pending'
                      ? <span className="text-xs text-amber-600">รออนุมัติ</span>
                      : u.approval_status === 'rejected'
                        ? <span className="text-xs text-red-600">ไม่อนุมัติ</span>
                        : u.email_verified
                          ? <span className="text-xs text-green-600">ยืนยันแล้ว</span>
                          : <span className="text-xs text-yellow-600">รอยืนยัน</span>}
                  </td>
                  <td className="px-4 py-2.5 flex items-center gap-3">
                    <button onClick={() => toggleStatus(u)}
                      className={`text-xs hover:underline ${u.is_active ? 'text-red-500' : 'text-green-600'}`}>
                      {u.is_active ? 'ปิดใช้งาน' : 'เปิดใช้งาน'}
                    </button>
                    {canManageRoles && (
                      <select value={u.role} onChange={(e) => changeRole(u, e.target.value)}
                        className="text-xs rounded border border-gray-300 px-1.5 py-1 bg-white">
                        {[STUDENT, ADMIN, SUPERADMIN].map((r) => (
                          <option key={r} value={r}>{roleLabel(r)}</option>
                        ))}
                      </select>
                    )}
                    {!u.is_active && canManageRoles && (
                      <button onClick={() => deleteUser(u)}
                        className="text-xs text-red-700 hover:underline font-medium">
                        ลบถาวร
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.items.length === 0 && <EmptyState className="py-10">ไม่พบผู้ใช้</EmptyState>}
        </div>
      )}

      <Pagination page={page} total={data.total} pageSize={20} onChange={setPage} />

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

      {showAdd && (
        <AddUserModal
          onClose={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); setPage(1); load() }}
        />
      )}

      {studyTarget && (
        <StudyEditModal
          user={studyTarget}
          onClose={() => setStudyTarget(null)}
          onSaved={() => { setStudyTarget(null); load() }}
        />
      )}
    </div>
  )
}

// แก้ปีที่เข้าศึกษา/จำนวนปี/เทียบโอนรายคน (เฟส 10) — เคสพิเศษที่สูตรอัตโนมัติไม่ตรง (ย้ายสาขา/รหัสผิด/
// เทียบโอนที่ยังไม่ได้ตั้งค่า) บังคับเหตุผลเสมอเพราะกระทบกฎจ่ายของ
function StudyEditModal({ user, onClose, onSaved }) {
  const [enrollmentYear, setEnrollmentYear] = useState(user.enrollment_year ?? '')
  const [studyYears, setStudyYears] = useState(user.study_years ?? 4)
  const [isTransfer, setIsTransfer] = useState(!!user.is_transfer)
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    if (!reason.trim()) { setError('กรุณาระบุเหตุผลที่แก้ไข'); return }
    const payload = {
      enrollment_year: enrollmentYear === '' ? null : Number(enrollmentYear),
      is_transfer: isTransfer,
      reason: reason.trim(),
    }
    // ส่ง study_years เฉพาะตอนแก้ค่าจริงเท่านั้น (ไม่ใช่ส่งค่าเดิมซ้ำทุกครั้งเหมือนเดิม) — ผู้ใช้เก่า/นำเข้า
    // ที่ study_years ค้างนอกช่วง 2-4 (ก่อนแผนจำกัดช่วง — ดู CLAUDE.md) ต้องแก้ enrollment_year/is_transfer
    // ได้โดยไม่ต้องแก้ study_years ก่อนเสมอไป ไม่งั้น backend ปฏิเสธ 422 (ge=2,le=4) จากค่าเดิมที่ส่งซ้ำมาเอง
    // ทั้งที่ผู้ใช้ไม่ได้ตั้งใจแก้ฟิลด์นี้เลย (แก้ตามรีวิวรอบ 4, M-c) — เช็คช่วง 2-4 เฉพาะตอนจะส่งจริงเท่านั้น
    // (เคลียร์ช่อง "จำนวนปี" ทั้งหมดแล้วส่งไปตรง ๆ จะได้ study_years: 0 → backend 422 ด้วย detail เป็น array
    // ของ object ซึ่ง setError(array) เดิมเอาไป render ตรง ๆ แล้ว React crash — ตรวจก่อนส่งเลย รีวิวรอบ 3, MINOR-4)
    if (Number(studyYears) !== Number(user.study_years ?? 4)) {
      const years = Number(studyYears)
      if (studyYears === '' || !Number.isInteger(years) || years < 2 || years > 4) {
        setError('จำนวนปีที่ควรเรียนจบต้องเป็นจำนวนเต็ม 2-4 ปี')
        return
      }
      payload.study_years = years
    }
    setSaving(true); setError('')
    try {
      await usersApi.updateStudy(user.id, payload)
      onSaved()
    } catch (err) {
      setError(errMsg(err, 'บันทึกไม่สำเร็จ'))
      setSaving(false)
    }
  }

  const input = 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500'

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center px-4 z-50">
      <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-2xl shadow-lg p-6 space-y-3">
        <h2 className="text-lg font-bold text-gray-800">แก้ไขชั้นปี</h2>
        <p className="text-sm text-gray-500">{user.full_name} ({user.student_id})</p>
        {error && <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>}

        <label className="block text-xs font-medium text-gray-600">ปีที่เข้าศึกษา (พ.ศ.)</label>
        <input className={input} type="number" min={2500} max={2700} value={enrollmentYear}
          onChange={(e) => setEnrollmentYear(e.target.value)} placeholder="เช่น 2569" />

        <label className="block text-xs font-medium text-gray-600">จำนวนปีที่ควรเรียนจบ</label>
        <input className={input} type="number" min={2} max={4} value={studyYears}
          onChange={(e) => setStudyYears(e.target.value)} />

        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={isTransfer} onChange={(e) => setIsTransfer(e.target.checked)}
            className="rounded border-gray-300" />
          นักศึกษาเทียบโอน
        </label>

        <label className="block text-xs font-medium text-gray-600">เหตุผล *</label>
        <input className={input} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="เช่น ย้ายสาขามาเทียบโอน / รหัสไม่ตรงรูปแบบเดิม" />

        <div className="flex gap-2 pt-2">
          <button type="button" onClick={onClose}
            className="flex-1 rounded-full border border-gray-300 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            ยกเลิก
          </button>
          <button type="submit" disabled={saving}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {saving ? 'กำลังบันทึก…' : 'บันทึก'}
          </button>
        </div>
      </form>
    </div>
  )
}

function AddUserModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    role: 'student', title: '', first_name: '', last_name: '', email: '', phone: '', password: '',
    student_id: '', username: '', major: 'comp_eng',
  })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setSaving(true)
    // ส่งเฉพาะ field ที่เกี่ยวกับ role นั้น ๆ (ค่าว่าง -> undefined)
    const payload = {
      role: form.role,
      full_name: `${form.title} ${form.first_name.trim()} ${form.last_name.trim()}`.trim(),
      email: form.email,
      password: form.password,
      phone: form.phone || undefined,
      student_id: form.role === 'student' ? form.student_id || undefined : undefined,
      major: form.role === 'student' ? form.major : undefined,
      username: form.role === 'admin' ? form.username || undefined : undefined,
    }
    try {
      await usersApi.create(payload)
      onCreated()
    } catch (err) {
      // detail อาจเป็น string (HTTPException) หรือ array ของ Pydantic error object (validation error)
      const detail = err.response?.data?.detail
      setError(Array.isArray(detail) ? detail.map((d) => d.msg).join(', ') : (detail ?? 'สร้างบัญชีไม่สำเร็จ'))
    } finally {
      setSaving(false)
    }
  }

  const input = 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500'

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center px-4 z-50">
      <form onSubmit={submit} className="w-full max-w-md bg-white rounded-2xl shadow-lg p-6 space-y-3">
        <h2 className="text-lg font-bold text-gray-800">เพิ่มผู้ใช้ใหม่</h2>

        {error && <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>}

        <div className="flex gap-2">
          {[STUDENT, ADMIN].map((r) => (
            <button type="button" key={r} onClick={() => setForm({ ...form, role: r })}
              className={`flex-1 rounded-lg py-2 text-sm font-medium border ${form.role === r ? 'bg-primary-600 text-white border-primary-600' : 'bg-white text-gray-600 border-gray-300'}`}>
              {r === 'student' ? 'นักศึกษา' : 'Admin'}
            </button>
          ))}
        </div>

        <div className="flex gap-2">
          <select
            className="w-28 flex-none rounded-lg border border-gray-300 px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            required value={form.title} onChange={set('title')}
          >
            <option value="">คำนำหน้า</option>
            {TITLES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <input className={input} placeholder="ชื่อ" required value={form.first_name} onChange={set('first_name')} />
          <input className={input} placeholder="นามสกุล" required value={form.last_name} onChange={set('last_name')} />
        </div>
        <input className={input} type="email" placeholder="อีเมล" required value={form.email} onChange={set('email')} />
        <input className={input} type="tel" placeholder="เบอร์โทรศัพท์ (ถ้ามี)" pattern="0\d{9}" value={form.phone} onChange={set('phone')} />
        <input className={input} type="password" placeholder="รหัสผ่าน" required minLength={6} value={form.password} onChange={set('password')} />

        {form.role === 'student' ? (
          <>
            <input className={input} placeholder="รหัสนักศึกษา" pattern="\d{10}" value={form.student_id} onChange={set('student_id')} />
            <select className={input} value={form.major} onChange={set('major')}>
              <option value="comp_eng">วิศวกรรมคอมพิวเตอร์</option>
              <option value="digital_design">ออกแบบดิจิทัล</option>
            </select>
          </>
        ) : (
          <input className={input} placeholder="รหัสประจำตัวอาจารย์/เจ้าหน้าที่ เช่น 01MNK01 (ใช้ล็อกอิน)"
            value={form.username} onChange={set('username')} />
        )}

        <div className="flex gap-2 pt-2">
          <button type="button" onClick={onClose}
            className="flex-1 rounded-full border border-gray-300 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
            ยกเลิก
          </button>
          <button type="submit" disabled={saving}
            className="flex-1 rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
            {saving ? 'กำลังสร้าง…' : 'สร้างบัญชี'}
          </button>
        </div>
      </form>
    </div>
  )
}
