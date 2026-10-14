import { useEffect, useRef, useState } from 'react'
import { changeRequestApi } from '../../api/changeRequestApi.js'
import EmptyState from '../../components/common/EmptyState.jsx'
import { formatDateTime } from '../../utils/formatDate.js'

const PING_COUNT = 5
const AUTO_REFRESH_MS = 10000
// เกณฑ์เวลาไป-กลับเฉลี่ยต่อ 1 คำขอ (ms) — หน้าเว็บ 1 หน้ายิง 3-6 คำขอ เกิน 600 ms ต่อคำขอผู้ใช้จะรู้สึกหน่วงชัดเจน
const LINK_WARN_MS = 150
const LINK_ERROR_MS = 600

const avg = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length

function summarizeLink(samples) {
  const totals = samples.map((s) => s.total)
  const server = avg(samples.map((s) => s.server))
  const total = avg(totals)
  return { total, server, overhead: Math.max(0, total - server), min: Math.min(...totals), max: Math.max(...totals) }
}

/** แปลงผลวัดเป็นการ์ดรูปแบบเดียวกับการ์ดสถานะจาก backend */
function linkCards(link) {
  if (!link) return [{ key: 'link', label: 'เวลาไป-กลับต่อ 1 คำขอ', status: 'ok', value: 'กำลังวัด…', hint: '' }]
  if (link.failed) {
    return [{ key: 'link', label: 'เวลาไป-กลับต่อ 1 คำขอ', status: 'error', value: 'ต่อหลังบ้านไม่ได้',
      hint: `สำเร็จ ${link.done}/${PING_COUNT} ครั้ง — ตรวจว่า backend/nginx ยังทำงานอยู่ และเครือข่ายของเครื่องนี้` }]
  }
  const status = link.total >= LINK_ERROR_MS ? 'error' : link.total >= LINK_WARN_MS ? 'warn' : 'ok'
  const onTheWay = link.overhead >= link.server
  const nav = performance.getEntriesByType?.('navigation')?.[0]
  const conn = navigator.connection
  const cards = [
    { key: 'link', label: `เวลาไป-กลับต่อ 1 คำขอ (เฉลี่ย ${PING_COUNT} ครั้ง)`, status,
      value: `${link.total.toFixed(0)} ms`,
      hint: `เร็วสุด ${link.min.toFixed(0)} · ช้าสุด ${link.max.toFixed(0)} ms`
        + (status === 'ok' ? '' : onTheWay
          ? ' — ช้าระหว่างทาง ไม่ใช่ที่เซิร์ฟเวอร์: ตรวจ Wi-Fi/เครือข่ายของเครื่องนี้ หรือ nginx'
          : ' — เซิร์ฟเวอร์ใช้เวลาประมวลผลนาน: ดูการ์ด "สถานะระบบ" ด้านล่าง') },
    { key: 'link_server', label: 'เวลาที่เซิร์ฟเวอร์ใช้ (รวมฐานข้อมูล)', status: link.server >= LINK_WARN_MS ? 'warn' : 'ok',
      value: `${link.server.toFixed(0)} ms`, hint: 'จาก header X-Process-Time ของคำขอเดียวกัน' },
    { key: 'link_overhead', label: 'เวลาที่เสียระหว่างทาง (เครือข่าย + nginx)',
      status: link.overhead >= LINK_ERROR_MS ? 'error' : link.overhead >= LINK_WARN_MS ? 'warn' : 'ok',
      value: `${link.overhead.toFixed(0)} ms`, hint: 'เวลาไป-กลับ ลบ เวลาที่เซิร์ฟเวอร์ใช้' },
  ]
  if (nav) {
    cards.push({ key: 'link_proto', label: 'รูปแบบการเชื่อมต่อของหน้านี้', status: 'ok',
      value: `${window.location.protocol.replace(':', '').toUpperCase()} · ${nav.nextHopProtocol || 'ไม่ทราบ'}`,
      hint: `โหลดหน้าเว็บครั้งแรก ${Math.round(nav.duration)} ms` })
  }
  if (conn?.effectiveType) {
    cards.push({ key: 'link_net', label: 'เครือข่ายของเครื่องนี้ (เบราว์เซอร์ประเมิน)',
      // ค่าประเมินของเบราว์เซอร์หยาบมาก (ต่อ localhost ยังขึ้น 3G ได้) — เตือนเฉพาะระดับที่ช้าจริง ตัวเลขชี้ขาดคือการ์ดเวลาไป-กลับ
      status: ['slow-2g', '2g'].includes(conn.effectiveType) ? 'warn' : 'ok',
      value: `${conn.effectiveType.toUpperCase()}${conn.downlink ? ` · ~${conn.downlink} Mbps` : ''}`,
      hint: conn.rtt != null ? `หน่วงโดยประมาณ ${conn.rtt} ms` : '' })
  }
  return cards
}

// หมวดของการ์ดฝั่งเซิร์ฟเวอร์ เรียงตามลำดับที่ใช้ไล่หาสาเหตุ: ช้าไหม → ฐานข้อมูล → เครื่อง → บริการ/งานค้าง
const SERVER_SECTIONS = [
  { id: 'speed', short: 'ความเร็ว', title: 'ความเร็วและการตอบสนองของหลังบ้าน',
    desc: 'ของผู้ใช้ทุกคนใน 5 นาทีล่าสุด — ช้าที่เซิร์ฟเวอร์เองหรือไม่ และช้าที่หน้าไหน',
    keys: ['api_speed', 'api_errors', 'event_loop'] },
  { id: 'db', short: 'ฐานข้อมูล', title: 'ฐานข้อมูล',
    desc: 'ต่อติดไหม · การเชื่อมต่อเต็มหรือไม่ · มีคำสั่งค้างหรือรอกันอยู่ไหม',
    keys: ['database', 'db_pool', 'db_connections', 'db_activity', 'db_size', 'migration'] },
  { id: 'host', short: 'เครื่อง', title: 'ทรัพยากรของเครื่อง',
    desc: 'CPU · หน่วยความจำ · ดิสก์ — ถ้าหมวดนี้เต็ม ทุกอย่างบนเครื่องจะช้าพร้อมกัน',
    keys: ['cpu_load', 'memory', 'disk', 'uploads', 'uptime'] },
  { id: 'service', short: 'บริการ', title: 'บริการและงานที่รอคน',
    desc: 'งานแจ้งเตือนอัตโนมัติ · อีเมล · ผู้ใช้ที่ออนไลน์ · งานค้างรอเจ้าหน้าที่',
    keys: ['scheduler', 'email', 'online_users', 'queue'] },
]

const STATUS_STYLE = {
  ok: { text: 'ปกติ', chip: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
  warn: { text: 'ต้องดู', chip: 'border-amber-200 bg-amber-50 text-amber-700' },
  error: { text: 'ผิดปกติ', chip: 'border-red-200 bg-red-50 text-red-700' },
}
const worst = (cards) => (cards.some((c) => c.status === 'error') ? 'error' : cards.some((c) => c.status === 'warn') ? 'warn' : 'ok')

/** หัวหมวด: เลขลำดับ + ชื่อ + คำอธิบายว่าหมวดนี้ตอบคำถามอะไร คั่นด้วยเส้นให้เห็นขอบเขตชัด */
function Section({ sec, children }) {
  return (
    <section id={sec.id} className="mb-10 scroll-mt-20">
      <div className="border-b border-gray-200 pb-2 mb-3">
        <h2 className="text-base font-semibold text-gray-800">{sec.no}. {sec.title}</h2>
        {sec.desc && <p className="text-xs text-gray-500 mt-0.5">{sec.desc}</p>}
      </div>
      {children}
    </section>
  )
}

function HealthCard({ h }) {
  return (
    <div className={`rounded-xl border px-4 py-3 ${
      h.status === 'error' ? 'border-red-200 bg-red-50'
        : h.status === 'warn' ? 'border-amber-200 bg-amber-50' : 'border-gray-200 bg-white'}`}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-gray-600">{h.label}</p>
        <span className={`text-xs font-semibold shrink-0 ${
          h.status === 'error' ? 'text-red-600' : h.status === 'warn' ? 'text-amber-600' : 'text-emerald-600'}`}>
          {h.status === 'error' ? '● ผิดปกติ' : h.status === 'warn' ? '● ต้องดู' : '● ปกติ'}
        </span>
      </div>
      <p className="text-lg font-light text-gray-800 mt-0.5 break-words">{h.value}</p>
      {h.hint && <p className="text-xs text-gray-500 mt-1">{h.hint}</p>}
    </div>
  )
}

/** หน้าตรวจสุขภาพข้อมูลสำหรับผู้ดูแลระบบสูงสุด — อ่านอย่างเดียว
 *  ทุกตัวเลขมาจาก query ที่เขียนไว้ล่วงหน้าใน backend (system_check_service) ไม่มีช่องพิมพ์ SQL
 *  โดยตั้งใจ: ช่องรัน SQL ในเว็บทำให้ลบ audit log ของตัวเองได้ ซึ่งขัดกับข้อกำหนดเรื่องประวัติที่ลบไม่ได้ */
export default function SystemCheckPage() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [link, setLink] = useState(null)       // ผลวัดการเชื่อมต่อจากเบราว์เซอร์นี้
  const [auto, setAuto] = useState(false)
  const busy = useRef(false)

  // ยิง /health 5 ครั้งติดกัน — ครั้งเดียวบอกอะไรไม่ได้ (ครั้งแรกมักรวมเวลาเปิดการเชื่อมต่อ) ต้องดูทั้งเฉลี่ยและช้าสุด
  const measureLink = async () => {
    const samples = []
    try {
      for (let i = 0; i < PING_COUNT; i += 1) samples.push(await changeRequestApi.ping())
      setLink(summarizeLink(samples))
    } catch {
      setLink({ failed: true, done: samples.length })
    }
  }

  // silent=true ตอนตรวจอัตโนมัติ — ไม่สลับทั้งหน้าเป็น "กำลังตรวจ…" ทุกรอบ
  const load = (silent = false) => {
    if (busy.current) return
    busy.current = true
    if (!silent) setLoading(true)
    measureLink()
    changeRequestApi.systemCheck()
      .then((d) => { setData(d); setError('') })
      .catch((err) => setError(err.response?.data?.detail ?? 'โหลดข้อมูลไม่สำเร็จ'))
      .finally(() => { busy.current = false; setLoading(false) })
  }
  useEffect(() => { load() }, [])
  useEffect(() => {
    if (!auto) return undefined
    const id = setInterval(() => load(true), AUTO_REFRESH_MS)
    return () => clearInterval(id)
  }, [auto])

  if (loading) return <EmptyState>กำลังตรวจ…</EmptyState>
  if (error) return <EmptyState>{error}</EmptyState>

  // จัดการ์ดเข้าหมวดตาม key — การ์ดที่ backend เพิ่มใหม่แต่ยังไม่ได้ใส่หมวด จะไปอยู่ "อื่น ๆ" ไม่หายไปเงียบ ๆ
  const byKey = Object.fromEntries((data.health ?? []).map((h) => [h.key, h]))
  const grouped = new Set(SERVER_SECTIONS.flatMap((g) => g.keys))
  const rest = (data.health ?? []).filter((h) => !grouped.has(h.key))
  const sections = [
    { id: 'link', short: 'การเชื่อมต่อ', title: 'การเชื่อมต่อหน้าบ้าน ↔ หลังบ้าน',
      desc: 'วัดจากเบราว์เซอร์ของเครื่องนี้ — ถ้าช้าตรงนี้แต่หมวดอื่นปกติ ปัญหาอยู่ที่เครือข่ายของเครื่องนี้หรือ nginx', cards: linkCards(link) },
    ...SERVER_SECTIONS.map((g) => ({ ...g, cards: g.keys.map((k) => byKey[k]).filter(Boolean) })),
    ...(rest.length ? [{ id: 'other', short: 'อื่น ๆ', title: 'อื่น ๆ', desc: '', cards: rest }] : []),
  ].filter((sec) => sec.cards.length).map((sec, idx) => ({ ...sec, no: idx + 1 }))

  return (
    <div className="px-6 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-light text-gray-800">ตรวจสอบระบบ</h1>
          <p className="text-xs text-gray-500 mt-1">
            ตรวจล่าสุด {formatDateTime(data.checked_at)} · อ่านอย่างเดียว ไม่มีการแก้ไขข้อมูลจากหน้านี้
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-gray-600">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} className="rounded border-gray-300" />
            ตรวจอัตโนมัติทุก {AUTO_REFRESH_MS / 1000} วินาที
          </label>
          <button onClick={() => load()}
            className="rounded-full border border-primary-300 px-4 py-1.5 text-sm font-medium text-primary-700 hover:bg-primary-50">
            ตรวจใหม่
          </button>
        </div>
      </div>

      {/* แถบสรุปบนสุด — ตอบคำถามแรก "ตอนนี้มีอะไรผิดปกติไหม" โดยไม่ต้องไล่อ่านทุกการ์ด กดแล้วเลื่อนไปหมวดนั้น */}
      <div className="flex flex-wrap gap-2 mb-8">
        {sections.map((sec) => {
          const st = worst(sec.cards)
          return (
            <a key={sec.id} href={`#${sec.id}`} className={`rounded-full border px-3 py-1 text-xs font-medium ${STATUS_STYLE[st].chip}`}>
              {sec.no}. {sec.short} · {STATUS_STYLE[st].text}
            </a>
          )
        })}
        <a href="#data" className={`rounded-full border px-3 py-1 text-xs font-medium ${STATUS_STYLE.ok.chip}`}>
          {sections.length + 1}. ข้อมูลในระบบ
        </a>
        <a href="#issues" className={`rounded-full border px-3 py-1 text-xs font-medium ${STATUS_STYLE[data.issues.length ? 'warn' : 'ok'].chip}`}>
          {sections.length + 2}. ข้อมูลที่ควรตรวจสอบ · {data.issues.length ? `${data.issues.length} เรื่อง` : 'ไม่พบ'}
        </a>
      </div>

      {sections.map((sec) => (
        <Section key={sec.id} sec={sec}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {sec.cards.map((h) => <HealthCard key={h.key} h={h} />)}
          </div>
          {sec.id === 'speed' && (
            <div className="mt-3">
              <p className="text-xs font-medium text-gray-600 mb-1.5">เส้นทางที่ช้าที่สุด (5 นาทีล่าสุด ของผู้ใช้ทุกคน)</p>
              {(data.slowest_endpoints ?? []).length === 0 ? (
                <div className="bg-white rounded-xl border border-gray-200 px-4 py-4 text-sm text-gray-500">ยังไม่มีข้อมูล</div>
              ) : (
                <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
                  <table className="w-full text-sm">
            <thead className="text-xs text-gray-500 text-left">
              <tr>
                <th className="px-4 py-2 font-medium">เส้นทาง</th>
                <th className="px-4 py-2 font-medium text-right">จำนวนครั้ง</th>
                <th className="px-4 py-2 font-medium text-right">เฉลี่ย (ms)</th>
                <th className="px-4 py-2 font-medium text-right">95% ไม่เกิน (ms)</th>
                <th className="px-4 py-2 font-medium text-right">ช้าสุด (ms)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.slowest_endpoints.map((e) => (
                <tr key={e.path}>
                  <td className="px-4 py-2 font-mono text-xs text-gray-700 break-all">{e.path}</td>
                  <td className="px-4 py-2 text-right text-gray-600">{e.count}</td>
                  <td className="px-4 py-2 text-right text-gray-600">{e.avg_ms}</td>
                  <td className={`px-4 py-2 text-right font-medium ${e.p95_ms >= 800 ? 'text-red-600' : 'text-gray-800'}`}>{e.p95_ms}</td>
                  <td className="px-4 py-2 text-right text-gray-600">{e.max_ms}</td>
                </tr>
              ))}
            </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </Section>
      ))}

      <Section sec={{ id: 'data', no: sections.length + 1, title: 'ข้อมูลในระบบ', desc: 'จำนวนแถวของแต่ละตาราง และขนาดไฟล์แนบ' }}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {data.counts.map((c) => (
          <div key={c.table} className="bg-white rounded-xl border border-gray-200 px-4 py-3">
            <p className="text-xs text-gray-500">{c.label}</p>
            <p className="text-2xl font-light text-gray-800">{c.count.toLocaleString('th-TH')}</p>
          </div>
        ))}
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-xs text-gray-500">ขนาดไฟล์แนบทั้งหมด</p>
          <p className="text-2xl font-light text-gray-800">{data.uploads_size_mb} MB</p>
          <p className="text-[10px] text-gray-400 font-mono">uploads/</p>
        </div>
      </div>
      </Section>

      <Section sec={{ id: 'issues', no: sections.length + 2, title: 'ข้อมูลที่ควรตรวจสอบ',
        desc: 'ความผิดปกติของข้อมูลที่ควรตามแก้ — ไม่กระทบความเร็วของระบบ' }}>
      {data.issues.length === 0 ? (
        <div className="bg-white rounded-xl border border-green-200 px-4 py-6 text-center text-sm text-green-700">
          ไม่พบความผิดปกติของข้อมูล
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 divide-y">
          {data.issues.map((i) => (
            <div key={i.key} className="px-4 py-3 flex items-start gap-4">
              <span className="rounded-full bg-amber-100 text-amber-700 text-xs font-semibold px-2 py-0.5 shrink-0">
                {i.count}
              </span>
              <div className="min-w-0">
                <p className="text-sm text-gray-800">{i.label}</p>
                <p className="text-xs text-gray-500">{i.hint}</p>
                {i.sample?.length > 0 && (
                  <p className="text-[11px] text-gray-400 font-mono mt-1 break-words">
                    เช่น {i.sample.join(' · ')}{i.count > i.sample.length && ` … และอีก ${i.count - i.sample.length} รายการ`}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      </Section>

      {data.audit_log_since && (
        <p className="text-xs text-gray-400 mt-6">
          ประวัติการใช้งานเก็บย้อนหลังตั้งแต่ {formatDateTime(data.audit_log_since)}
        </p>
      )}
    </div>
  )
}
