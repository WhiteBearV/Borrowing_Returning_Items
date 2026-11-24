import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { stocktakeApi } from '../../api/stocktakeApi.js'
import QrScanModal from '../../components/common/QrScanModal.jsx'
import StatusBadge from '../../components/equipment/StatusBadge.jsx'
import StocktakeConditionDialog, { CONDITIONS } from '../../components/equipment/StocktakeConditionDialog.jsx'
import StocktakeSheetPreview from '../../components/equipment/StocktakeSheetPreview.jsx'
import { downloadBlob } from '../../utils/csv.js'
import { formatDate, formatDateTime, todayTH } from '../../utils/formatDate.js'
import { openPdf } from '../../utils/openPdf.js'

// ตรวจครุภัณฑ์รายห้อง (16 พ.ย. 69 — feedback ผู้ดูแลคลัง): สแกน QR หน้าห้อง → รายการที่ควรมี → เดินสแกนทีละชิ้น → ปิดรอบ
const RESULT = {
  pending: { label: 'ยังไม่พบ', cls: 'bg-gray-100 text-gray-600' },
  found: { label: 'พบ', cls: 'bg-green-100 text-green-800' },
  moved_here: { label: 'ย้ายมา', cls: 'bg-orange-100 text-orange-800' },
  on_loan: { label: 'ถูกยืมอยู่', cls: 'bg-blue-100 text-blue-800' },
  missing: { label: 'ไม่พบ', cls: 'bg-red-100 text-red-800' },
  elsewhere: { label: 'พบที่ห้องอื่น', cls: 'bg-amber-100 text-amber-800' },
}
const ORDER = ['pending', 'missing', 'elsewhere', 'moved_here', 'on_loan', 'found']

export default function StocktakePage() {
  const [params, setParams] = useSearchParams()
  const [locations, setLocations] = useState([])
  const [rounds, setRounds] = useState([])
  const [round, setRound] = useState(null)
  const [scanning, setScanning] = useState(false)
  const [flash, setFlash] = useState(null) // { ok, text }
  const [finishing, setFinishing] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [roomQuery, setRoomQuery] = useState('')
  const [previewing, setPreviewing] = useState(false)
  const [summaryOpen, setSummaryOpen] = useState(false) // พรีวิวใบรวมทุกห้อง
  const roundId = round?.id
  const loadRoundSheet = useCallback(() => stocktakeApi.reportPreview(roundId), [roundId])
  const [marking, setMarking] = useState(null) // แถวที่กำลังเลือกสภาพ (หลังสแกน/กดจากรายการ)
  const [openRoom, setOpenRoom] = useState(null) // ห้องที่กาง "ดูของในห้อง" อยู่
  const [roomItems, setRoomItems] = useState(null) // null = กำลังโหลด
  const [itemQuery, setItemQuery] = useState('')

  const err = (e, fallback) => setError(e.response?.data?.detail ?? fallback)

  const loadLists = useCallback(() => {
    stocktakeApi.locations().then(setLocations).catch((e) => err(e, 'โหลดรายชื่อห้องไม่สำเร็จ'))
    stocktakeApi.rounds().then(setRounds).catch(() => {})
  }, [])

  // ดูของในห้องคร่าว ๆ ก่อนตรวจจริง — อ่านอย่างเดียว ไม่เปิดรอบ (เปิดรอบ = ลง DB + audit)
  const toggleRoom = (location) => {
    if (openRoom === location) { setOpenRoom(null); return }
    setOpenRoom(location)
    setRoomItems(null)
    setItemQuery('')
    stocktakeApi.roomItems(location).then(setRoomItems).catch((e) => { setOpenRoom(null); err(e, 'โหลดรายการในห้องไม่สำเร็จ') })
  }

  const start = async (location) => {
    setError('')
    setBusy(true)
    try {
      setRound(await stocktakeApi.start(location))
      setScanning(true)
    } catch (e) {
      err(e, 'เปิดรอบตรวจไม่สำเร็จ')
    } finally {
      setBusy(false)
    }
  }

  // มาจาก QR หน้าห้อง (?location=…) → เปิด/เข้ารอบของห้องนั้นทันที แล้วลบพารามิเตอร์ทิ้ง
  // ไม่งั้นกดรีเฟรชหลังปิดรอบ = เปิดรอบใหม่เงียบ ๆ (เจอตอนทดสอบเว็บ 16 พ.ย.) — รีเฟรชแล้วไปหน้ารายการห้องแทน (มีปุ่ม "ตรวจต่อ")
  const qrLocation = params.get('location')
  useEffect(() => {
    if (qrLocation) {
      start(qrLocation)
      setParams({}, { replace: true })
    } else if (!round) loadLists()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qrLocation])

  const handleScan = async (scanned) => {
    if (marking) return // กำลังเลือกสภาพชิ้นก่อนอยู่ — กล้องค้างเห็น QR ชิ้นอื่นไม่ต้องยิงซ้อน
    try {
      const res = await stocktakeApi.scan(round.id, scanned)
      setRound(res.round)
      setMarking(res.item) // เจอแล้วให้ผู้ตรวจเลือกสภาพทันที (สแกนซ้ำ = แก้สภาพเดิมได้)
      const name = `${res.item.equipment_code} ${res.item.equipment_name}`
      setFlash(res.outcome === 'moved_here'
        ? { ok: true, warn: true, text: `ย้ายมาห้องนี้: ${name} (เดิมอยู่ ${res.item.from_location || 'ไม่ระบุ'})` }
        : { ok: true, text: `${res.outcome === 'already' ? 'สแกนไปแล้ว' : 'พบ'}: ${name}` })
    } catch (e) {
      setFlash({ ok: false, text: e.response?.data?.detail ?? 'สแกนไม่สำเร็จ' })
    }
  }

  const undoScan = async () => {
    setRound(await stocktakeApi.undo(round.id, marking.id))
    setFlash({ ok: true, text: `ยกเลิกการสแกนแล้ว: ${marking.equipment_code} ${marking.equipment_name}` })
    setMarking(null)
  }

  const saveCondition = async (condition, note) => {
    setRound(await stocktakeApi.setCondition(round.id, marking.id, condition, note))
    setMarking(null)
  }

  const downloadSummaryXlsx = () => stocktakeApi.summaryXlsx()
    .then((b) => downloadBlob(b, `รายงานทะเบียนคุมทรัพย์สิน รวมทุกห้อง ${todayTH()}.xlsx`))
    .catch((e) => err(e, 'ดาวน์โหลด Excel ไม่สำเร็จ'))

  const downloadXlsx = () => stocktakeApi.reportXlsx(round.id)
    .then((b) => downloadBlob(b, `ใบตรวจครุภัณฑ์ ห้อง ${round.location} ${formatDate(round.started_at).replaceAll('/', '-')}.xlsx`))
    .catch((e) => err(e, 'ดาวน์โหลด Excel ไม่สำเร็จ'))

  const handleFinish = async () => {
    setBusy(true)
    try {
      setRound(await stocktakeApi.finish(round.id, note.trim()))
      setFinishing(false)
      setNote('')
    } catch (e) {
      err(e, 'ปิดรอบไม่สำเร็จ')
    } finally {
      setBusy(false)
    }
  }

  const backToList = () => {
    setRound(null)
    setFlash(null)
    setFinishing(false)
    setError('')
    loadLists()
  }

  if (round) {
    const items = [...round.items].sort((a, b) => ORDER.indexOf(a.result) - ORDER.indexOf(b.result))
    const pending = round.counts.pending ?? 0
    const done = !!round.finished_at
    const unmarked = round.items.filter((i) => ['found', 'moved_here'].includes(i.result) && !i.condition).length
    const condOf = (k) => CONDITIONS.find((c) => c.key === k)
    return (
      <div className="px-6 py-8 space-y-4">
        <button onClick={backToList} className="text-sm text-primary-600 hover:underline">← ห้องทั้งหมด</button>
        <div className="bg-white rounded-2xl shadow-sm p-5 space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h1 className="text-xl font-semibold text-gray-800">ตรวจครุภัณฑ์ห้อง {round.location}</h1>
            <span className="text-xs text-gray-500">
              <b className="text-gray-700">วันที่ตรวจ {formatDate(round.started_at)}</b> · เริ่ม {formatDateTime(round.started_at)}{round.started_by_name && ` · ${round.started_by_name}`}
              {done && ` · ปิดรอบ ${formatDateTime(round.finished_at)}`}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {ORDER.filter((k) => round.counts[k]).map((k) => (
              <span key={k} className={`rounded-full px-3 py-1 text-xs font-medium ${RESULT[k].cls}`}>
                {RESULT[k].label} {round.counts[k]}
              </span>
            ))}
          </div>
          {error && <p className="text-sm text-red-700 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
          {round.note && <p className="text-sm text-gray-600">หมายเหตุ: {round.note}</p>}
          <div className="flex flex-wrap gap-2">
            {!done && (
              <>
                <button onClick={() => { setFlash(null); setScanning(true) }}
                  className="rounded-full bg-primary-600 px-5 py-2 text-sm font-semibold text-white hover:bg-primary-700">
                  สแกนครุภัณฑ์
                </button>
                <button onClick={() => setFinishing((v) => !v)}
                  className="rounded-full border border-gray-300 px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
                  จบการตรวจ
                </button>
              </>
            )}
            <button onClick={() => openPdf(stocktakeApi.reportPdf(round.id)).catch((e) => err(e, 'เปิดใบตรวจไม่สำเร็จ'))}
              className="rounded-full border border-gray-300 px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              พิมพ์ใบตรวจครุภัณฑ์ (PDF)
            </button>
            <button onClick={() => setPreviewing(true)}
              className="rounded-full border border-gray-300 px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              ดูตัวอย่าง Excel
            </button>
            <button onClick={downloadXlsx}
              className="rounded-full border border-gray-300 px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              ดาวน์โหลด Excel
            </button>
          </div>
          {finishing && !done && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-2 text-sm">
              {unmarked > 0 && (
                <p className="font-medium text-red-700">พบแล้วแต่ยังไม่ได้เลือกสภาพ {unmarked} รายการ — กด "เลือกสภาพ" ที่รายการก่อนปิดรอบ</p>
              )}
              {pending > 0
                ? <p className="text-amber-900">ยังไม่ได้สแกน {pending} รายการ — ปิดรอบแล้วบันทึกว่า <b>ยังไม่พบ</b> และ<b>เว้นช่องสภาพไว้</b> (เผื่อไปเจอที่อื่นภายหลัง)</p>
                : <p className="text-amber-900">สแกนครบทุกรายการแล้ว</p>}
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={2000}
                placeholder="หมายเหตุ (ถ้ามี)"
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
              <button onClick={handleFinish} disabled={busy || unmarked > 0}
                className="rounded-full bg-amber-600 px-5 py-2 text-sm font-semibold text-white hover:bg-amber-700 disabled:opacity-50">
                ยืนยันปิดรอบ
              </button>
            </div>
          )}
        </div>

        <div className="bg-white rounded-2xl shadow-sm divide-y">
          {items.map((i) => (
            <div key={i.id} className={`flex items-center justify-between gap-3 px-4 py-3 ${i.result === 'moved_here' ? 'border-l-4 border-orange-400 bg-orange-50/40' : ''}`}>
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-800 truncate">{i.equipment_name}</p>
                <p className="text-xs text-gray-500">
                  {i.equipment_code}{i.asset_number && ` · ${i.asset_number}`}{i.location_detail && ` · ${i.location_detail}`}
                  {i.result === 'elsewhere' && ` · อยู่ที่ ${i.from_location}`}
                </p>
                {i.result === 'moved_here' && (
                  <span className="mt-1 inline-block rounded-md bg-orange-100 px-2 py-0.5 text-xs font-semibold text-orange-800">
                    ⚠ ไม่อยู่ในรายการห้องนี้ — ย้ายมาจาก {i.from_location || 'ไม่ระบุ'}
                  </span>
                )}
                {i.note && <p className="text-xs text-gray-600">หมายเหตุ: {i.note}</p>}
              </div>
              <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                {i.condition
                  ? <span className={`rounded-full px-3 py-1 text-xs font-medium ${condOf(i.condition)?.cls}`}>✓ {condOf(i.condition)?.label}</span>
                  : <span className={`rounded-full px-3 py-1 text-xs font-medium ${RESULT[i.result]?.cls}`}>{RESULT[i.result]?.label ?? i.result}</span>}
                {!done && (
                  <button onClick={() => setMarking(i)}
                    className={`rounded-full px-3 py-1 text-xs font-medium ${!i.condition && ['found', 'moved_here'].includes(i.result)
                      ? 'bg-primary-600 text-white hover:bg-primary-700' : 'border border-gray-300 text-gray-600 hover:bg-gray-50'}`}>
                    {i.condition ? 'แก้สภาพ' : 'เลือกสภาพ'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        {previewing && (
          <StocktakeSheetPreview load={loadRoundSheet} onDownload={downloadXlsx} onClose={() => setPreviewing(false)} />
        )}
        {marking && (
          <StocktakeConditionDialog key={marking.id} item={marking} roomName={round.location}
            onSave={saveCondition} onUndo={undoScan} onClose={() => setMarking(null)} />
        )}
        {scanning && (
          <QrScanModal continuous title={`สแกนครุภัณฑ์ — ${round.location}`} onResult={handleScan}
            onClose={() => setScanning(false)}>
            <p className="text-sm text-gray-600">
              พบแล้ว {(round.counts.found ?? 0) + (round.counts.moved_here ?? 0)} · ยังไม่พบ {pending}
            </p>
            {flash && (
              <p className={`text-sm rounded-lg px-3 py-2 ${!flash.ok ? 'bg-red-50 text-red-700'
                : flash.warn ? 'bg-orange-50 text-orange-800' : 'bg-green-50 text-green-800'}`}>
                {flash.text}
              </p>
            )}
          </QrScanModal>
        )}
      </div>
    )
  }

  const rq = roomQuery.trim().toLowerCase()
  const shownRooms = rq ? locations.filter((l) => l.location.toLowerCase().includes(rq)) : locations
  // เลขครุภัณฑ์พิมพ์ติดกันไม่มีขีดก็เจอ (เหมือนช่องค้นหาหลัก)
  const iq = itemQuery.trim().toLowerCase().replace(/-/g, '')
  const shownItems = (roomItems ?? []).filter((i) => !iq || [i.name, i.code, i.asset_number, i.serial_number, i.location_detail]
    .some((v) => v && v.toLowerCase().replace(/-/g, '').includes(iq)))

  return (
    <div className="px-6 py-8 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold text-gray-800">ตรวจครุภัณฑ์ประจำห้อง</h1>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setSummaryOpen(true)}
            className="rounded-full bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700">
            ใบตรวจรวมทุกห้อง
          </button>
          <button onClick={() => openPdf(stocktakeApi.summaryPdf()).catch((e) => err(e, 'เปิดใบรวมไม่สำเร็จ'))}
            className="rounded-full border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            ใบรวม (PDF)
          </button>
          <button onClick={() => openPdf(stocktakeApi.roomQrPdf()).catch((e) => err(e, 'สร้าง QR ไม่สำเร็จ'))}
            className="rounded-full border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            พิมพ์ QR ทุกห้อง
          </button>
        </div>
      </div>
      <p className="text-sm text-gray-500">
        ติด QR หน้าห้อง แล้วสแกนด้วยมือถือเพื่อเริ่มตรวจ หรือกดเริ่มจากรายการด้านล่าง · ตรวจเฉพาะ<b>ครุภัณฑ์</b> (ตามทะเบียนคุมทรัพย์สิน ไม่รวมวัสดุ) · ห้องมาจากช่อง "ห้อง" ของอุปกรณ์
        (ชื่อต้องตรงกันทุกตัวอักษร · ตู้/ชั้นกรอกที่ช่อง "ตำแหน่งในห้อง" ไม่แยกเป็นห้องใหม่)
      </p>
      {error && <p className="text-sm text-red-700 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

      <input value={roomQuery} onChange={(e) => setRoomQuery(e.target.value)} placeholder="ค้นหาห้อง เช่น 15310, 5304"
        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />

      <div className="bg-white rounded-2xl shadow-sm divide-y">
        {locations.length === 0 && <p className="px-4 py-6 text-sm text-gray-500">ยังไม่มีอุปกรณ์ที่ระบุสถานที่เก็บ</p>}
        {locations.length > 0 && shownRooms.length === 0 && (
          <p className="px-4 py-6 text-sm text-gray-500">ไม่พบห้องที่มีคำว่า "{roomQuery}"</p>
        )}
        {shownRooms.map((l) => (
          <div key={l.location}>
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
            <div>
              <p className="text-sm font-medium text-gray-800">{l.location}</p>
              <p className="text-xs text-gray-500">{l.count} รายการตามทะเบียน{l.open_round_id && ' · มีรอบที่ยังตรวจไม่จบ'}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => toggleRoom(l.location)}
                className="rounded-full border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50">
                {openRoom === l.location ? 'ซ่อนรายการ' : 'ดูของในห้อง'}
              </button>
              <button onClick={() => openPdf(stocktakeApi.roomQrPdf(l.location)).catch((e) => err(e, 'สร้าง QR ไม่สำเร็จ'))}
                className="rounded-full border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50">
                QR ห้อง
              </button>
              <button onClick={() => start(l.location)} disabled={busy}
                className="rounded-full bg-primary-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-primary-700 disabled:opacity-50">
                {l.open_round_id ? 'ตรวจต่อ' : 'เริ่มตรวจ'}
              </button>
            </div>
          </div>
          {openRoom === l.location && (
            <div className="bg-gray-50 px-4 py-3 space-y-2">
              {roomItems === null ? <p className="text-sm text-gray-500">กำลังโหลด…</p> : (
                <>
                  <input value={itemQuery} onChange={(e) => setItemQuery(e.target.value)}
                    placeholder="หาในห้องนี้ — ชื่อ / รหัส / เลขครุภัณฑ์ / SN"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500" />
                  <p className="text-xs text-gray-500">
                    ตามทะเบียน {roomItems.length} รายการ · ถูกยืมอยู่ {roomItems.filter((i) => i.holder_name).length} ·
                    ดูอย่างเดียว ยังไม่ได้เริ่มรอบตรวจ
                  </p>
                  <ul className="divide-y rounded-lg bg-white max-h-96 overflow-y-auto">
                    {shownItems.map((i) => (
                      <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                        <div className="min-w-0">
                          <p className="text-sm text-gray-800">{i.name}</p>
                          {i.location_detail && <p className="text-xs font-medium text-amber-700">ตำแหน่ง: {i.location_detail}</p>}
                          <p className="text-xs text-gray-500">
                            {i.code}{i.asset_number && ` · ${i.asset_number}`}{i.serial_number && ` · SN ${i.serial_number}`}
                          </p>
                        </div>
                        {i.holder_name
                          ? <span className="text-xs text-primary-700">ยืมโดย {i.holder_name}{i.due_date && ` · คืน ${formatDate(i.due_date)}`}</span>
                          : <StatusBadge status={i.status} />}
                      </li>
                    ))}
                    {shownItems.length === 0 && <li className="px-3 py-3 text-sm text-gray-500">ไม่พบในห้องนี้</li>}
                  </ul>
                </>
              )}
            </div>
          )}
          </div>
        ))}
      </div>

      {rounds.length > 0 && (
        <div className="bg-white rounded-2xl shadow-sm">
          <h2 className="px-4 pt-4 text-sm font-semibold text-gray-700">ประวัติการตรวจ</h2>
          <div className="divide-y">
            {rounds.map((r) => (
              <button key={r.id} onClick={() => stocktakeApi.get(r.id).then(setRound).catch((e) => err(e, 'โหลดไม่สำเร็จ'))}
                className="w-full flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-left hover:bg-gray-50">
                <span className="text-sm text-gray-800">{r.location}
                  <span className="ml-2 text-xs text-gray-500">{formatDateTime(r.started_at)}</span>
                </span>
                <span className="text-xs text-gray-600">
                  {r.finished_at
                    ? ORDER.filter((k) => r.counts[k]).map((k) => `${RESULT[k].label} ${r.counts[k]}`).join(' · ')
                    : 'กำลังตรวจ'}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
      {summaryOpen && (
        <StocktakeSheetPreview load={stocktakeApi.summaryPreview} onDownload={downloadSummaryXlsx}
          onClose={() => setSummaryOpen(false)} />
      )}
    </div>
  )
}
