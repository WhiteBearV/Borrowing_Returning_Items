import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext.jsx'
import { CartProvider } from './context/CartContext.jsx'
import ProtectedRoute from './components/layout/ProtectedRoute.jsx'

import LoginPage from './pages/LoginPage.jsx'
import RegisterPage from './pages/RegisterPage.jsx'
import VerifyEmailPage from './pages/VerifyEmailPage.jsx'
import ForgotPasswordPage from './pages/ForgotPasswordPage.jsx'
import ResetPasswordPage from './pages/ResetPasswordPage.jsx'

// Student pages
import StudentDashboard from './pages/student/DashboardPage.jsx'
import EquipmentListPage from './pages/student/EquipmentListPage.jsx'
import EquipmentDetailPage from './pages/student/EquipmentDetailPage.jsx'
import BorrowRequestPage from './pages/student/BorrowRequestPage.jsx'
import MyBorrowsPage from './pages/student/MyBorrowsPage.jsx'
import ProfilePage from './pages/student/ProfilePage.jsx'

// หลัง deploy ชื่อไฟล์ chunk เปลี่ยน แท็บที่เปิดค้างจากเวอร์ชันก่อนจะโหลด chunk เก่าไม่เจอ (404) → โหลดหน้าใหม่ 1 ครั้ง
// ให้ได้ index.html ตัวใหม่ · ธงใน sessionStorage กันวนรีโหลดไม่จบถ้าไฟล์หายจริง
const lazyPage = (load) => lazy(() => load().then(
  (m) => { sessionStorage.removeItem('chunk-reload'); return m },
  (err) => {
    if (sessionStorage.getItem('chunk-reload')) throw err
    sessionStorage.setItem('chunk-reload', '1')
    window.location.reload()
    return new Promise(() => {})
  },
))

// Admin pages — โหลดเมื่อเข้าหน้านั้นจริง นักศึกษา (ผู้ใช้ส่วนใหญ่) ไม่ต้องดาวน์โหลดโค้ดฝั่งเจ้าหน้าที่ (QA รอบ 2: JS ไฟล์เดียว 600 kB)
const AdminDashboard = lazyPage(() => import('./pages/admin/DashboardPage.jsx'))
const EquipmentManagePage = lazyPage(() => import('./pages/admin/EquipmentManagePage.jsx'))
const BundleManagePage = lazyPage(() => import('./pages/admin/BundleManagePage.jsx'))
const BorrowRequestsPage = lazyPage(() => import('./pages/admin/BorrowRequestsPage.jsx'))
const AllBorrowsPage = lazyPage(() => import('./pages/admin/AllBorrowsPage.jsx'))
const UsersPage = lazyPage(() => import('./pages/admin/UsersPage.jsx'))
const AuditLogPage = lazyPage(() => import('./pages/admin/AuditLogPage.jsx'))
const SettingsPage = lazyPage(() => import('./pages/admin/SettingsPage.jsx'))
const ChangeRequestsPage = lazyPage(() => import('./pages/admin/ChangeRequestsPage.jsx'))
const SystemCheckPage = lazyPage(() => import('./pages/admin/SystemCheckPage.jsx'))
const UtilizationPage = lazyPage(() => import('./pages/admin/UtilizationPage.jsx'))
const FinesPage = lazyPage(() => import('./pages/admin/FinesPage.jsx'))
const EligibleStudentsPage = lazyPage(() => import('./pages/admin/EligibleStudentsPage.jsx'))

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <CartProvider>
        <Suspense fallback={null}>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />

          {/* Student routes */}
          <Route element={<ProtectedRoute role="student" />}>
            <Route path="/dashboard" element={<StudentDashboard />} />
          </Route>

          {/* หน้ายืม/โปรไฟล์ ใช้ร่วมกัน — admin ยืมเองได้ (อาจารย์เบิกของให้ นศ. ทำ Lab) */}
          <Route element={<ProtectedRoute />}>
            <Route path="/equipment" element={<EquipmentListPage />} />
            <Route path="/equipment/:id" element={<EquipmentDetailPage />} />
            <Route path="/borrow" element={<BorrowRequestPage />} />
            <Route path="/my-borrows" element={<MyBorrowsPage />} />
            <Route path="/profile" element={<ProfilePage />} />
          </Route>

          {/* Admin routes */}
          <Route element={<ProtectedRoute role="admin" />}>
            <Route path="/admin/dashboard" element={<AdminDashboard />} />
            <Route path="/admin/equipment" element={<EquipmentManagePage />} />
            <Route path="/admin/bundles" element={<BundleManagePage />} />
            <Route path="/admin/borrow-requests" element={<BorrowRequestsPage />} />
            <Route path="/admin/borrows" element={<AllBorrowsPage />} />
            <Route path="/admin/utilization" element={<UtilizationPage />} />
            <Route path="/admin/fines" element={<FinesPage />} />
            <Route path="/admin/my-borrows" element={<MyBorrowsPage />} />
            <Route path="/admin/users" element={<UsersPage />} />
            <Route path="/admin/eligible-students" element={<EligibleStudentsPage />} />
            <Route path="/admin/audit" element={<AuditLogPage />} />
            <Route path="/admin/change-requests" element={<ChangeRequestsPage />} />
          </Route>

          {/* เฉพาะผู้ดูแลระบบสูงสุด — ต้องกันที่ route ด้วย ไม่ใช่แค่ซ่อนเมนู (พิมพ์ URL ตรงก็เข้าได้) */}
          <Route element={<ProtectedRoute role="admin" />}>
            {/* ผู้ดูแลคลังเข้าได้ แต่แก้ได้เฉพาะค่ากลุ่มงานประจำ (backend กันรายคีย์ ดู ADMIN_EDITABLE_KEYS) */}
            <Route path="/admin/settings" element={<SettingsPage />} />
          </Route>
          <Route element={<ProtectedRoute role="superadmin" />}>
            <Route path="/admin/system-check" element={<SystemCheckPage />} />
          </Route>

          <Route path="/" element={<Navigate to="/login" replace />} />
          {/* URL ที่ไม่มีอยู่ — เดิมขึ้นหน้าขาวเปล่า (R3-07) ส่งกลับหน้าแรก ProtectedRoute พาต่อเอง: ยังไม่ล็อกอิน → login · เจ้าหน้าที่ → /admin/dashboard) */}
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
        </Suspense>
        </CartProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
