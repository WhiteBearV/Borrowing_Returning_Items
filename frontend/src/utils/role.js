// ระดับสิทธิ์ผู้ใช้ — ต้องตรงกับ backend app/utils/roles.py เสมอ
// เดิมคำว่า "Admin" ถูก hardcode ไว้หลายที่ พอเพิ่มระดับใหม่จะลืมแก้ที่ใดที่หนึ่ง

export const SUPERADMIN = 'superadmin'
export const ADMIN = 'admin'
export const STUDENT = 'student'

// ทุกระดับ เรียงจากสูงไปต่ำ — ใช้เติมตัวเลือกใน dropdown ทุกที่ ไม่ต้องเขียนรายการมือซ้ำ
// (เดิมหน้า Audit เขียนมือแล้วลืม superadmin จนกรองหาการกระทำของผู้ดูแลระบบสูงสุดไม่ได้)
export const ALL_ROLES = [SUPERADMIN, ADMIN, STUDENT]

export const ROLE_LABEL = {
  [SUPERADMIN]: 'ผู้ดูแลระบบสูงสุด',
  [ADMIN]: 'ผู้ดูแลคลัง',
  [STUDENT]: 'ผู้ใช้งาน',
}

// สีป้าย — ต้องแยกออกจากกันชัดพอให้เหลือบตาแล้วรู้ว่าตอนนี้ล็อกอินสิทธิ์ไหนอยู่
export const ROLE_BADGE_CLASS = {
  [SUPERADMIN]: 'bg-rose-100 text-rose-700',
  [ADMIN]: 'bg-purple-100 text-purple-700',
  [STUDENT]: 'bg-gray-100 text-gray-600',
}

export const roleLabel = (role) => ROLE_LABEL[role] ?? role
export const roleBadgeClass = (role) => ROLE_BADGE_CLASS[role] ?? ROLE_BADGE_CLASS[STUDENT]

/** เจ้าหน้าที่ (ผู้ดูแลคลังขึ้นไป) — ใช้แทนการเทียบ role === 'admin' ทุกที่
 *  ไม่งั้น superadmin จะกลายเป็นสิทธิ์ "น้อยกว่า" admin ซึ่งผิดความตั้งใจ */
export const isStaff = (user) => user?.role === ADMIN || user?.role === SUPERADMIN
export const isSuperadmin = (user) => user?.role === SUPERADMIN
