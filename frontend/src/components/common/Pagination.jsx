export default function Pagination({ page, total, pageSize, onChange }) {
  const totalPages = Math.ceil(total / pageSize)
  if (totalPages <= 1) return null

  const go = (p) => onChange(Math.min(Math.max(1, p), totalPages))

  return (
    <div className="flex justify-center items-center gap-2 mt-8 flex-wrap">
      <button
        disabled={page <= 1}
        onClick={() => go(page - 5)}
        className="px-2 py-1 text-sm rounded border disabled:opacity-30 hover:bg-gray-50"
      >« -5</button>
      <button
        disabled={page <= 1}
        onClick={() => go(page - 1)}
        className="px-3 py-1 text-sm rounded border disabled:opacity-30 hover:bg-gray-50"
      >← ก่อนหน้า</button>

      <div className="flex items-center gap-1.5 text-sm text-gray-600">
        <span>หน้า</span>
        <select
          value={page}
          onChange={(e) => go(Number(e.target.value))}
          className="rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <span>/ {totalPages}</span>
      </div>

      <button
        disabled={page >= totalPages}
        onClick={() => go(page + 1)}
        className="px-3 py-1 text-sm rounded border disabled:opacity-30 hover:bg-gray-50"
      >ถัดไป →</button>
      <button
        disabled={page >= totalPages}
        onClick={() => go(page + 5)}
        className="px-2 py-1 text-sm rounded border disabled:opacity-30 hover:bg-gray-50"
      >+5 »</button>
    </div>
  )
}
