import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext.jsx'
import { CartProvider } from './context/CartContext.jsx'
import ProtectedRoute from './components/layout/ProtectedRoute.jsx'

import LoginPage from './pages/LoginPage.jsx'
import RegisterPage from './pages/RegisterPage.jsx'
import VerifyEmailPage from './pages/VerifyEmailPage.jsx'

// Student pages
import StudentDashboard from './pages/student/DashboardPage.jsx'
import EquipmentListPage from './pages/student/EquipmentListPage.jsx'
import EquipmentDetailPage from './pages/student/EquipmentDetailPage.jsx'
import BorrowRequestPage from './pages/student/BorrowRequestPage.jsx'
import MyBorrowsPage from './pages/student/MyBorrowsPage.jsx'
import ProfilePage from './pages/student/ProfilePage.jsx'

// Admin pages
import AdminDashboard from './pages/admin/DashboardPage.jsx'
import EquipmentManagePage from './pages/admin/EquipmentManagePage.jsx'
import BorrowRequestsPage from './pages/admin/BorrowRequestsPage.jsx'
import AllBorrowsPage from './pages/admin/AllBorrowsPage.jsx'
import UsersPage from './pages/admin/UsersPage.jsx'
import AuditLogPage from './pages/admin/AuditLogPage.jsx'
import SettingsPage from './pages/admin/SettingsPage.jsx'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <CartProvider>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />

          {/* Student routes */}
          <Route element={<ProtectedRoute role="student" />}>
            <Route path="/dashboard" element={<StudentDashboard />} />
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
            <Route path="/admin/borrow-requests" element={<BorrowRequestsPage />} />
            <Route path="/admin/borrows" element={<AllBorrowsPage />} />
            <Route path="/admin/users" element={<UsersPage />} />
            <Route path="/admin/audit" element={<AuditLogPage />} />
            <Route path="/admin/settings" element={<SettingsPage />} />
          </Route>

          <Route path="/" element={<Navigate to="/login" replace />} />
        </Routes>
        </CartProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
