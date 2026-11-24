import { Fragment, useEffect, useState } from 'react'
import { useAuthContext } from '../../context/AuthContext.jsx'
import { authApi } from '../../api/authApi.js'
import { LATEST_PATCH, PATCH_NOTES, itemsFor } from '../../data/patchNotes.js'
import { isStaff, isSuperadmin } from '../../utils/role.js'
import { formatDate } from '../../utils/formatDate.js'

// สีหัวกลุ่มแบบโน้ตแพตช์เกม — แต่ละตำแหน่งคนละสี อ่านแล้วรู้ทันทีว่าข้อไหนของใคร
const GROUPS = [
  { key: 'all', label: 'ทุกคน', bar: 'from-primary-700 to-primary-500', dot: 'bg-primary-600' },
  { key: 'student', label: 'ผู้ยืม', bar: 'from-sky-500 to-cyan-400', dot: 'bg-sky-500' },
  { key: 'staff', label: 'เจ้าหน้าที่', bar: 'from-amber-500 to-orange-400', dot: 'bg-amber-500' },
  { key: 'superadmin', label: 'ผู้ดูแลระบบสูงสุด', bar: 'from-rose-500 to-pink-500', dot: 'bg-rose-500' },
]

// ป้ายต่อข้อ: ใหม่ = ไม่มีของเดิม · ปรับ = มีวิธีใหม่แต่วิธีเดิมยังใช้ได้ (still) · เปลี่ยน = วิธีเดิมใช้ไม่ได้แล้ว
const KIND = {
  new: { label: 'ใหม่', cls: 'bg-emerald-100 text-emerald-800' },
  tweak: { label: 'ปรับ', cls: 'bg-sky-100 text-sky-800' },
  change: { label: 'เปลี่ยน', cls: 'bg-amber-100 text-amber-800' },
}
const kindOf = (it) => (it.still ? 'tweak' : it.before ? 'change' : 'new')

/** ข้อความในเครื่องหมายคำพูด = ชื่อปุ่ม/เมนูบนจอ → ตัวหนาสีเข้ม (ป้ายเหลืองเดิมรกตา — ผู้ใช้ 24 พ.ย. 69) */
function Highlight({ text }) {
  return text.split(/"([^"]+)"/).map((part, i) => (i % 2
    ? <strong key={i} className="font-bold text-primary-800">{part}</strong>
    : <Fragment key={i}>{part}</Fragment>))
}

/** ไอคอนโน้ตบนแถบหัว + โมดัล Patch Note (23 พ.ย. 69)
 *  เด้งเองครั้งแรกหลังอัปเดต (user.seen_patch ≠ เวอร์ชันล่าสุด) · กดรับทราบแล้วจำในบัญชี เปลี่ยนเครื่องก็ไม่เด้งซ้ำ
 *  บัญชีที่สร้างหลังวันอัปเดตไม่เด้ง (ไม่มี "แบบเดิม" ให้เทียบ) แค่บันทึกเงียบ ๆ */
export default function PatchNoteModal() {
  const { user, setUser } = useAuthContext()
  const unseen = user.seen_patch !== LATEST_PATCH
  const [open, setOpen] = useState(false)
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    if (!unseen) return
    const isNewAccount = user.created_at?.slice(0, 10) >= PATCH_NOTES[0].date
    if (isNewAccount) markSeen()
    else setOpen(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unseen])

  async function markSeen() {
    try {
      await authApi.markPatchSeen(LATEST_PATCH)
      setUser((u) => ({ ...u, seen_patch: LATEST_PATCH }))
    } catch { /* ไม่สำเร็จ = เด้งอีกครั้งรอบหน้า ไม่เป็นไร */ }
  }

  const close = () => { setOpen(false); setIdx(0); if (unseen) markSeen() }
  const note = PATCH_NOTES[idx]
  const items = itemsFor(note, { staff: isStaff(user), superadmin: isSuperadmin(user) })
  const count = (k) => items.filter((it) => kindOf(it) === k).length

  return (
    <>
      <button onClick={() => setOpen(true)} title="มีอะไรใหม่" aria-label="มีอะไรใหม่ (Patch Note)"
        className="relative p-1.5 rounded-lg text-gray-600 hover:bg-gray-100">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M8 13h8M8 17h5" />
        </svg>
        {unseen && <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-rose-500 animate-pulse" />}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-2 sm:p-4" onClick={close}>
          <div className="flex max-h-[96vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}>
            {/* แบนเนอร์หัว */}
            <div className="relative shrink-0 bg-gradient-to-br from-slate-900 via-indigo-900 to-primary-700 px-5 py-4 text-white sm:px-7 sm:py-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-yellow-400 px-2.5 py-0.5 text-xs font-bold tracking-widest text-slate-900">PATCH NOTES</span>
                <span className="rounded-full border border-white/30 px-2.5 py-0.5 text-xs font-semibold">v{note.version}</span>
                {PATCH_NOTES.length > 1 && (
                  <select value={idx} onChange={(e) => setIdx(Number(e.target.value))}
                    className="ml-auto rounded-md bg-white/10 px-2 py-1 text-xs text-white">
                    {PATCH_NOTES.map((n, i) => <option key={n.version} value={i} className="text-gray-900">{n.title}</option>)}
                  </select>
                )}
              </div>
              <h2 className="mt-2 text-2xl font-extrabold sm:text-3xl">{note.title}</h2>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                <span className="text-white/70">อัปเดตวันที่ {formatDate(note.date)}</span>
                {Object.entries(KIND).map(([k, v]) => count(k) > 0 && (
                  <span key={k} className={`rounded-md px-2 py-0.5 text-xs font-bold ${v.cls}`}>{v.label} {count(k)}</span>
                ))}
              </div>
            </div>

            {/* รายการ แยกกลุ่มตามตำแหน่ง */}
            <div className="flex-1 space-y-5 overflow-y-auto bg-slate-50 px-4 py-4 sm:px-6">
              {GROUPS.map((g) => {
                const list = items.filter((it) => it.for === g.key)
                if (!list.length) return null
                return (
                  <section key={g.key}>
                    <h3 className={`mb-2 inline-block rounded-r-full bg-gradient-to-r ${g.bar} py-1 pl-3 pr-5 text-sm font-bold text-white shadow`}>
                      สำหรับ{g.label}
                    </h3>
                    <ol className="space-y-2.5">
                      {list.map((it, i) => (
                        <li key={i} className="rounded-xl border border-gray-200 bg-white p-3.5 shadow-sm sm:p-4">
                          <div className="flex items-start gap-2">
                            <span className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[11px] font-extrabold tracking-wide ${KIND[kindOf(it)].cls}`}>
                              {KIND[kindOf(it)].label}
                            </span>
                            <p className="text-base font-bold text-gray-900 sm:text-lg"><Highlight text={it.title} /></p>
                          </div>
                          {it.before && (
                            <p className="mt-2 flex gap-2 text-sm text-gray-500 sm:text-base">
                              <span className="shrink-0 rounded bg-rose-100 px-1.5 font-semibold text-rose-700">เดิม</span>
                              <span className="line-through decoration-rose-400/70">{it.before}</span>
                            </p>
                          )}
                          <p className="mt-2 flex gap-2 text-sm leading-relaxed text-gray-800 sm:text-base">
                            <span className="h-fit shrink-0 rounded bg-emerald-100 px-1.5 font-semibold text-emerald-700">
                              {it.before ? 'ตอนนี้' : 'วิธีใช้'}
                            </span>
                            <span><Highlight text={it.now} /></span>
                          </p>
                          {it.still && (
                            <p className="mt-2 flex gap-2 text-sm leading-relaxed text-gray-600 sm:text-base">
                              <span className="h-fit shrink-0 rounded bg-sky-100 px-1.5 font-semibold text-sky-700">ยังใช้ได้</span>
                              <span><Highlight text={it.still} /></span>
                            </p>
                          )}
                        </li>
                      ))}
                    </ol>
                  </section>
                )
              })}
            </div>

            <div className="flex shrink-0 items-center justify-between gap-2 border-t border-gray-200 bg-white px-5 py-3">
              <span className="text-xs text-gray-500 sm:text-sm">เปิดอ่านอีกครั้งได้ที่ไอคอนโน้ตด้านบน</span>
              <button onClick={close} className="rounded-full bg-primary-600 px-6 py-2 text-sm font-bold text-white shadow hover:bg-primary-700 sm:text-base">
                รับทราบ
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
