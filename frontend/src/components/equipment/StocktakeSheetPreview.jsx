import { useEffect, useState } from 'react'

const TICK_COLS = [5, 6, 7, 8, 9] // ปกติ … รายการผิดประเภท (0-based) — ตรงกับคอลัมน์ F–J ในไฟล์
const LEFT_COLS = [2, 13, 17] // รายการ / ชื่อห้อง / หมายเหตุ ชิดซ้าย

/** พรีวิวใบตรวจแบบ Excel บนหน้าเว็บ (รายห้อง/รวมทุกห้อง — load = ฟังก์ชันดึงข้อมูล) — ข้อมูลมาจาก backend ชุดเดียวกับไฟล์ .xlsx (ไม่ต้องโหลดไฟล์มาเปิดดูทุกครั้ง) */
export default function StocktakeSheetPreview({ load, onDownload, onClose }) {
  const [sheet, setSheet] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    load().then(setSheet).catch((e) => setError(e.response?.data?.detail ?? 'โหลดตัวอย่างไม่สำเร็จ'))
  }, [load])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-3 py-4 backdrop-blur-sm">
      <div className="flex max-h-full w-full max-w-7xl flex-col rounded-2xl bg-white shadow-xl">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-5 py-3">
          <h2 className="font-bold text-gray-800">ตัวอย่างไฟล์ Excel</h2>
          <div className="flex gap-2">
            <button onClick={onDownload}
              className="rounded-full bg-primary-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-primary-700">
              ดาวน์โหลด Excel
            </button>
            <button onClick={onClose}
              className="rounded-full border border-gray-300 px-4 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50">
              ปิด
            </button>
          </div>
        </div>

        <div className="overflow-auto p-4">
          {!sheet ? <p className="text-sm text-gray-500">{error || 'กำลังโหลด…'}</p> : (
            <>
              <div className="mb-2 flex flex-wrap justify-between gap-2 text-sm">
                <div className="space-y-0.5 font-semibold text-gray-800">
                  <p>{sheet.inspector}</p>
                  <p>{sheet.room}</p>
                </div>
                <div className="space-y-0.5 text-right font-semibold text-gray-800">
                  <p>{sheet.org}</p>
                  <p>{sheet.title}</p>
                  <p>{sheet.date}</p>
                </div>
              </div>
              <table className="min-w-max border-collapse text-xs">
                <thead>
                  <tr>
                    <th className="border border-gray-400 bg-gray-50 px-1 text-gray-400" />
                    {sheet.headers.map((h, c) => (
                      <th key={h + c} className="whitespace-pre-line border border-gray-400 bg-gray-100 px-2 py-1 font-semibold text-gray-700">
                        <span className="block text-[10px] font-normal text-gray-400">{String.fromCharCode(65 + c)}</span>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sheet.rows.map((row, r) => (
                    <tr key={r}>
                      <td className="border border-gray-400 bg-gray-50 px-1 text-center text-gray-400">{r + 5}</td>
                      {row.map((v, c) => (
                        <td key={c} className={`border border-gray-300 px-2 py-1 ${TICK_COLS.includes(c) ? 'text-center text-base font-bold text-green-700'
                          : LEFT_COLS.includes(c) ? 'max-w-xs text-left' : c === 3 ? 'text-right' : 'text-center'}`}>
                          {v ?? ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                  <tr>
                    <td className="border border-gray-400 bg-gray-50 px-1 text-center text-gray-400">{sheet.rows.length + 5}</td>
                    <td colSpan={2} className="border border-gray-300 px-2 py-1 text-right font-semibold">รวมทั้งสิ้น</td>
                    <td className="border border-gray-300 px-2 py-1 text-right font-semibold">{sheet.total}</td>
                    <td colSpan={sheet.headers.length - 3} className="border border-gray-300" />
                  </tr>
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
