import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { authApi } from '../api/authApi.js'

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const [state, setState] = useState('loading') // loading | success | error
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    const token = searchParams.get('token')
    if (!token) {
      setState('error')
      setErrorMsg('ไม่พบ token ในลิงก์')
      return
    }
    authApi.verifyEmail(token)
      .then(() => setState('success'))
      .catch((err) => {
        setState('error')
        setErrorMsg(err.response?.data?.detail ?? 'ยืนยันอีเมลไม่สำเร็จ')
      })
  }, []) // ponytail: searchParams ไม่ใส่ deps — token อ่านครั้งเดียวตอน mount

  if (state === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-500 text-sm">กำลังยืนยันอีเมล…</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow p-8 text-center">
        {state === 'success' ? (
          <>
            <div className="text-4xl mb-4">✅</div>
            <h2 className="text-xl font-light text-gray-800 mb-2">ยืนยันอีเมลสำเร็จ</h2>
            <p className="text-sm text-gray-500 mb-6">คุณสามารถเข้าสู่ระบบได้แล้ว</p>
            <Link
              to="/login"
              className="inline-block rounded-full bg-primary-600 px-6 py-2 text-sm font-semibold text-white hover:bg-primary-700 transition-colors"
            >
              เข้าสู่ระบบ
            </Link>
          </>
        ) : (
          <>
            <div className="text-4xl mb-4">❌</div>
            <h2 className="text-xl font-light text-gray-800 mb-2">ยืนยันอีเมลไม่สำเร็จ</h2>
            <p className="text-sm text-red-600 mb-6">{errorMsg}</p>
            <Link to="/login" className="text-primary-600 hover:underline text-sm font-medium">
              กลับไปหน้าเข้าสู่ระบบ
            </Link>
          </>
        )}
      </div>
    </div>
  )
}
