import { Navigate, Outlet } from 'react-router-dom'
import { useAuthContext } from '../../context/AuthContext.jsx'
import Sidebar from './Sidebar.jsx'

export default function ProtectedRoute({ role }) {
  const { user, loading } = useAuthContext()

  if (loading) return <div className="flex items-center justify-center h-screen text-gray-400 text-sm">Loading…</div>
  if (!user) return <Navigate to="/login" replace />
  if (role && user.role !== role) {
    return <Navigate to={user.role === 'admin' ? '/admin/dashboard' : '/dashboard'} replace />
  }

  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
