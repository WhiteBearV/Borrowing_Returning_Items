import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { authApi } from '../api/authApi.js'

const MAJORS = [
  { value: 'comp_eng', label: 'วิศวกรรมคอมพิวเตอร์' },
  { value: 'digital_design', label: 'ออกแบบดิจิทัล' },
]

const TITLES = ['นาย', 'นาง', 'นางสาว']

// หลักสูตร (เฟส 10) — แสดงให้ทุกคนเลือกได้ตั้งแต่ตอนสมัคร (ไม่ใช่แค่คนที่ระบบรู้ว่าเป็นรุ่นเทียบโอน) กัน
// ต้องมี endpoint ที่บอกได้ว่ารหัสนี้อยู่ในรายชื่อหรือไม่ (ข้อมูลส่วนบุคคล) — backend ตรวจกับรายชื่อจริงอีกที
const TRANSFER_YEARS = [2, 3, 4]

export default function RegisterPage() {
  const [form, setForm] = useState({
    title: '',
    first_name: '',
    last_name: '',
    student_id: '',
    email: '',
    phone: '',
    password: '',
    confirm_password: '',
    major: '',
    pdpa_consent: false,
    is_transfer: false,
    study_years: 4,
  })
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  // พรีวิวปีการศึกษา/ชั้นปีใต้ช่องรหัสนักศึกษา (เฟส 10) — คำนวณจากรหัสอย่างเดียว ไม่ค้นรายชื่อ
  const [yearPreview, setYearPreview] = useState(null)

  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value })

  useEffect(() => {
    const sid = form.student_id.trim()
    if (!/^\d{10}$/.test(sid)) { setYearPreview(null); return }
    let cancelled = false
    authApi.studyYearPreview(sid).then((p) => { if (!cancelled) setYearPreview(p) }).catch(() => { if (!cancelled) setYearPreview(null) })
    return () => { cancelled = true }
  }, [form.student_id])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (form.password !== form.confirm_password) {
      setError('รหัสผ่านทั้งสองช่องไม่ตรงกัน')
      return
    }
    setLoading(true)
    try {
      await authApi.register({
        full_name: `${form.title} ${form.first_name.trim()} ${form.last_name.trim()}`.trim(),
        student_id: form.student_id.trim(),
        email: form.email.trim(),
        phone: form.phone.trim(),
        password: form.password,
        pdpa_consent: form.pdpa_consent,
        major: form.major,
        is_transfer: form.is_transfer,
        study_years: form.is_transfer ? Number(form.study_years) : 4,
      })
      setSuccess(true)
    } catch (err) {
      // detail อาจเป็น string (HTTPException) หรือ array ของ Pydantic error object (validation error)
      const detail = err.response?.data?.detail
      setError(Array.isArray(detail) ? detail.map((d) => d.msg).join(', ') : (detail ?? 'ลงทะเบียนไม่สำเร็จ'))
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-sm bg-white rounded-2xl shadow p-8 text-center">
          <div className="text-4xl mb-4">📧</div>
          <h2 className="text-xl font-light text-gray-800 mb-2">ตรวจสอบอีเมลของคุณ</h2>
          <p className="text-sm text-gray-500 mb-6">
            เราส่งลิงก์ยืนยันไปที่ <span className="font-medium text-gray-700">{form.email}</span> แล้ว
            กรุณากดลิงก์ในอีเมลก่อนเข้าสู่ระบบ
          </p>
          <Link to="/login" className="text-primary-600 hover:underline text-sm font-medium">
            กลับไปหน้าเข้าสู่ระบบ
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4 py-12">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow p-8">
        <h1 className="text-2xl font-light text-gray-800 mb-1">ลงทะเบียน</h1>
        <p className="text-sm text-gray-500 mb-6">ระบบยืม-คืนอุปกรณ์</p>

        {error && (
          <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex gap-2">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                คำนำหน้า <span className="text-red-500">*</span>
              </label>
              <select
                required
                value={form.title}
                onChange={set('title')}
                className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
              >
                <option value="">—</option>
                {TITLES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                ชื่อ <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                required
                autoFocus
                value={form.first_name}
                onChange={set('first_name')}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                placeholder="ชื่อจริง"
              />
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                นามสกุล <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                required
                value={form.last_name}
                onChange={set('last_name')}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                placeholder="นามสกุล"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              รหัสนักศึกษา <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              pattern="\d{10}"
              value={form.student_id}
              onChange={set('student_id')}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="65XXXXXXXX"
            />
            {/* พรีวิวปีการศึกษา/ชั้นปีจากรหัส (เฟส 10) — คำนวณอย่างเดียว ไม่ได้ยืนยันว่าอยู่ในรายชื่อจริง */}
            {yearPreview && (
              <p className="mt-1 text-xs text-gray-500">
                ปีการศึกษา {yearPreview.academic_year} · ชั้นปีที่ {yearPreview.year_level}
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">หลักสูตร</label>
            <div className="flex gap-2">
              {[{ v: false, label: 'ปกติ 4 ปี' }, { v: true, label: 'เทียบโอน' }].map((opt) => (
                <button type="button" key={String(opt.v)}
                  onClick={() => setForm({ ...form, is_transfer: opt.v, study_years: opt.v ? form.study_years : 4 })}
                  className={`flex-1 rounded-lg py-2 text-sm font-medium border ${
                    form.is_transfer === opt.v ? 'bg-primary-600 text-white border-primary-600' : 'bg-white text-gray-600 border-gray-300'
                  }`}>
                  {opt.label}
                </button>
              ))}
            </div>
            {form.is_transfer && (
              <select value={form.study_years} onChange={set('study_years')}
                className="mt-2 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                {TRANSFER_YEARS.map((y) => <option key={y} value={y}>เทียบโอน {y} ปี</option>)}
              </select>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              อีเมล <span className="text-red-500">*</span>
            </label>
            <input
              type="email"
              required
              value={form.email}
              onChange={set('email')}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="email@cdti.ac.th"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              เบอร์โทรศัพท์ <span className="text-red-500">*</span>
            </label>
            <input
              type="tel"
              required
              pattern="0\d{9}"
              value={form.phone}
              onChange={set('phone')}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="08XXXXXXXX"
            />
            <p className="mt-1 text-xs text-gray-400">กรอกตัวเลข 10 หลัก ไม่ต้องใส่ขีด</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              รหัสผ่าน <span className="text-red-500">*</span>
            </label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                required
                minLength={8}
                value={form.password}
                onChange={set('password')}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                placeholder="อย่างน้อย 8 ตัวอักษร"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? 'ซ่อนรหัสผ่าน' : 'แสดงรหัสผ่าน'}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showPassword ? '🙈' : '👁️'}
              </button>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              ยืนยันรหัสผ่าน <span className="text-red-500">*</span>
            </label>
            <div className="relative">
              <input
                type={showConfirm ? 'text' : 'password'}
                required
                minLength={8}
                value={form.confirm_password}
                onChange={set('confirm_password')}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                placeholder="กรอกรหัสผ่านอีกครั้ง"
              />
              <button
                type="button"
                onClick={() => setShowConfirm((v) => !v)}
                aria-label={showConfirm ? 'ซ่อนรหัสผ่าน' : 'แสดงรหัสผ่าน'}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showConfirm ? '🙈' : '👁️'}
              </button>
            </div>
            {form.confirm_password && form.password !== form.confirm_password && (
              <p className="mt-1 text-xs text-red-500">รหัสผ่านต้องตรงกัน</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              สาขา <span className="text-red-500">*</span>
            </label>
            <select
              required
              value={form.major}
              onChange={set('major')}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white"
            >
              <option value="">— เลือกสาขา —</option>
              {MAJORS.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
            {/* เฟส 9: ระบบยึดสาขาตามรายชื่อที่สาขารับรอง — บอกไว้ตั้งแต่ตอนกรอก
                กันความเข้าใจผิดว่าเลือกอะไรก็ได้ และกันคนตกใจตอนเห็นสาขาในโปรไฟล์ไม่ตรงที่เลือก */}
            <p className="mt-1 text-xs text-gray-400">
              ระบบจะยืนยันชื่อและสาขากับรายชื่อที่สาขาส่งให้อีกครั้ง
              ถ้าไม่พบรหัสของคุณในรายชื่อ จะสมัครได้แต่ต้องรอเจ้าหน้าที่อนุมัติก่อนเข้าใช้งาน
            </p>
          </div>

          <div className="space-y-2">
            <details className="rounded-lg border border-gray-200 px-3 py-2 text-xs text-gray-500">
              <summary className="cursor-pointer select-none font-medium text-gray-600">
                คำชี้แจงเกี่ยวกับการใช้ข้อมูลส่วนบุคคล
              </summary>
              <p className="mt-2 leading-relaxed">
                ข้อมูลที่ท่านให้ไว้ในแบบประเมินฉบับนี้จะถูกใช้เพื่อวัตถุประสงค์ในการประเมินผลและปรับปรุงกระบวนการรับสมัครนักศึกษาเท่านั้น
                โดยจะมีการเก็บรักษาข้อมูลอย่างเหมาะสมและไม่เปิดเผยต่อบุคคลภายนอกโดยไม่ได้รับอนุญาต ทั้งนี้
                รายละเอียดเกี่ยวกับการคุ้มครองข้อมูลส่วนบุคคลสามารถศึกษาเพิ่มเติมได้ที่{' '}
                <a
                  href="https://www.cdti.ac.th/protection-of-personal-information"
                  target="_blank" rel="noreferrer"
                  className="text-primary-600 hover:underline"
                >
                  https://www.cdti.ac.th/protection-of-personal-information
                </a>
              </p>
            </details>
            <label className="flex items-start gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                required
                checked={form.pdpa_consent}
                onChange={(e) => setForm({ ...form, pdpa_consent: e.target.checked })}
                className="mt-0.5 rounded border-gray-300"
              />
              <span>ข้าพเจ้าได้อ่านและยอมรับคำชี้แจงเกี่ยวกับการใช้ข้อมูลส่วนบุคคลข้างต้น <span className="text-red-500">*</span></span>
            </label>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-full bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'กำลังลงทะเบียน…' : 'ลงทะเบียน'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-gray-500">
          มีบัญชีแล้ว?{' '}
          <Link to="/login" className="text-primary-600 hover:underline font-medium">
            เข้าสู่ระบบ
          </Link>
        </p>
      </div>
    </div>
  )
}
