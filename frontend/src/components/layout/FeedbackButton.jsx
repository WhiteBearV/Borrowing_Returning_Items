import { useEffect, useMemo, useState } from 'react'
import { feedbackApi } from '../../api/feedbackApi.js'

const MAX_FILES = 3
const KINDS = [['bug', 'แจ้งปัญหา / บั๊ก'], ['suggestion', 'ข้อเสนอแนะ']]

// ปุ่ม "แจ้งปัญหา" บนแถบหัวทุกหน้าที่ล็อกอินแล้ว (3 พ.ย. 69) — ส่งรายละเอียด + ภาพหน้าจอถึงผู้พัฒนาทางอีเมล
export default function FeedbackButton() {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState('bug')
  const [detail, setDetail] = useState('')
  const [files, setFiles] = useState([])
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const previews = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files])
  useEffect(() => () => previews.forEach(URL.revokeObjectURL), [previews])

  const close = () => { setOpen(false); setDetail(''); setFiles([]); setError(''); setDone(false); setKind('bug') }

  const addFiles = (e) => {
    const picked = [...files, ...e.target.files].slice(0, MAX_FILES)
    setFiles(picked)
    e.target.value = ''
  }

  const submit = async (e) => {
    e.preventDefault()
    setSending(true)
    setError('')
    try {
      await feedbackApi.send({ kind, detail, files })
      setDone(true)
    } catch (err) {
      setError(err.response?.data?.detail ?? 'ส่งไม่สำเร็จ กรุณาลองใหม่')
    } finally {
      setSending(false)
    }
  }

  return (
    <>
      <button onClick={() => setOpen(true)} title="แจ้งปัญหา / ข้อเสนอแนะ" aria-label="แจ้งปัญหา / ข้อเสนอแนะ"
        className="p-1.5 rounded-lg text-gray-600 hover:bg-gray-100">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /><path d="M12 7v4M12 14h.01" />
        </svg>
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={close}>
          <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            {done ? (
              <div className="text-center space-y-3">
                <p className="text-lg font-semibold text-gray-800">ส่งเรียบร้อยแล้ว ขอบคุณครับ/ค่ะ</p>
                <p className="text-sm text-gray-500">ผู้พัฒนาจะตรวจสอบและติดต่อกลับทางอีเมลของคุณหากต้องการข้อมูลเพิ่ม</p>
                <button onClick={close} className="rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white">ปิด</button>
              </div>
            ) : (
              <form onSubmit={submit} className="space-y-3">
                <h2 className="text-lg font-semibold text-gray-800">แจ้งปัญหา / ข้อเสนอแนะ</h2>
                <div className="flex gap-2">
                  {KINDS.map(([v, label]) => (
                    <button type="button" key={v} onClick={() => setKind(v)}
                      className={`flex-1 rounded-lg border py-2 text-sm font-medium ${kind === v
                        ? 'bg-primary-600 text-white border-primary-600' : 'bg-white text-gray-600 border-gray-300'}`}>
                      {label}
                    </button>
                  ))}
                </div>
                <textarea required value={detail} onChange={(e) => setDetail(e.target.value)} rows={5} maxLength={5000}
                  placeholder={kind === 'bug'
                    ? 'เกิดอะไรขึ้น ทำอะไรอยู่ตอนนั้น และคาดว่าควรเป็นอย่างไร'
                    : 'อยากให้ระบบปรับปรุงหรือเพิ่มอะไร'}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                <div>
                  <label className="text-sm text-gray-600">
                    รูปหลักฐาน / ภาพหน้าจอ (ไม่เกิน {MAX_FILES} รูป รูปละ 5MB)
                  </label>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {previews.map((src, i) => (
                      <div key={src} className="relative">
                        <img src={src} alt="" className="h-16 w-16 rounded-lg border object-cover" />
                        <button type="button" aria-label="ลบรูป" onClick={() => setFiles(files.filter((_, j) => j !== i))}
                          className="absolute -right-1.5 -top-1.5 h-5 w-5 rounded-full bg-gray-700 text-xs text-white">×</button>
                      </div>
                    ))}
                    {files.length < MAX_FILES && (
                      <label className="flex h-16 w-16 cursor-pointer items-center justify-center rounded-lg border-2 border-dashed border-gray-300 text-2xl text-gray-400 hover:border-primary-400">
                        +
                        <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple className="hidden" onChange={addFiles} />
                      </label>
                    )}
                  </div>
                </div>
                <p className="text-xs text-gray-400">ระบบจะแนบชื่อ อีเมล และหน้าที่คุณเปิดอยู่ไปด้วย เพื่อให้ติดต่อกลับได้</p>
                {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={close} className="rounded-full px-4 py-2 text-sm text-gray-600 hover:bg-gray-100">ยกเลิก</button>
                  <button type="submit" disabled={sending || !detail.trim()}
                    className="rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
                    {sending ? 'กำลังส่ง…' : 'ส่ง'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </>
  )
}
