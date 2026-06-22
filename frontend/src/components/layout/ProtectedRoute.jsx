import { Navigate, Outlet } from 'react-router-dom'
import { useAuthContext } from '../../context/AuthContext.jsx'

export default function ProtectedRoute({ role }) {
  const { user, loading } = useAuthContext()

  if (loading) return <div className="flex items-center justify-center h-screen">Loading...</div>
  if (!user) return <Navigate to="/login" replace />
  if (role && user.role !== role) {
    return <Navigate to={user.role === 'admin' ? '/admin/dashboard' : '/dashboard'} replace />
  }

  return <Outlet />
}
