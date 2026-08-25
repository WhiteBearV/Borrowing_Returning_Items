// ข้อความ "กำลังโหลด…" / "ไม่พบ…" ที่พิมพ์ซ้ำ ๆ กันทุกหน้าด้วย markup เดียวกันเป๊ะ — รวมไว้ที่เดียว
// ข้อความยังเป็นของแต่ละหน้าเหมือนเดิม (ผ่าน children) ไม่แตะ wording
export default function EmptyState({ children, className = 'py-16' }) {
  return <p className={`text-center text-gray-400 ${className}`}>{children}</p>
}
