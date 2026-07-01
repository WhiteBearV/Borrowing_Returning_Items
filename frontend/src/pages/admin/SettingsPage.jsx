import { useEffect, useState } from 'react'
import { settingsApi } from '../../api/settingsApi.js'

export default function SettingsPage() {
  const [settings, setSettings] = useState([])
  const [editing, setEditing] = useState({}) // { [key]: value }
  const [saving, setSaving] = useState({})   // { [key]: bool }
  const [saved, setSaved] = useState({})     // { [key]: bool } — flash feedback
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    settingsApi.list().then(setSettings).finally(() => setLoading(false))
  }, [])

  const save = async (key) => {
    const value = editing[key]
    if (value === undefined) return
    setSaving({ ...saving, [key]: true })
    try {
      await settingsApi.update(key, value)
      setSettings((prev) => prev.map((s) => s.key === key ? { ...s, value } : s))
      setEditing((prev) => { const next = { ...prev }; delete next[key]; return next })
      setSaved({ ...saved, [key]: true })
      setTimeout(() => setSaved((p) => { const n = { ...p }; delete n[key]; return n }), 2000)
    } finally {
      setSaving((prev) => { const next = { ...prev }; delete next[key]; return next })
    }
  }

  if (loading) return <p className="text-center text-gray-400 py-16">กำลังโหลด…</p>

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">การตั้งค่าระบบ</h1>

      <div className="bg-white rounded-xl border border-gray-200 divide-y">
        {settings.map((s) => {
          const isDirty = editing[s.key] !== undefined && editing[s.key] !== s.value
          return (
            <div key={s.key} className="px-5 py-4 flex items-start gap-4">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800">{s.description || s.key}</p>
                <p className="text-xs text-gray-400 font-mono mt-0.5">{s.key}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <input
                  type="number"
                  min={0}
                  value={editing[s.key] ?? s.value}
                  onChange={(e) => setEditing({ ...editing, [s.key]: e.target.value })}
                  className="w-20 rounded-lg border border-gray-300 px-2 py-1.5 text-sm text-center focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                {isDirty && (
                  <button
                    onClick={() => save(s.key)}
                    disabled={saving[s.key]}
                    className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {saving[s.key] ? '…' : 'บันทึก'}
                  </button>
                )}
                {saved[s.key] && !isDirty && (
                  <span className="text-xs text-green-600">✓</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
