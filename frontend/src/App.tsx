import { ResourceAdmin } from './ResourceAdmin'
import { OrganizationAdmin } from './OrganizationAdmin'
import { useCallback, useEffect, useState } from 'react'

type UserProfile = {
  id: string
  username: string
  display_name: string
  email: string | null
  enabled: boolean
}

type MeResponse = {
  data: UserProfile
}

type LiveStatus = {
  status: string
}

export function App() {
  const [backendStatus, setBackendStatus] = useState('checking')
  const [user, setUser] = useState<UserProfile | null>(null)
  const [authChecked, setAuthChecked] = useState(false)

  const loadMe = useCallback(async () => {
    try {
      const response = await fetch('/api/v1/auth/me', { credentials: 'same-origin' })
      if (response.status === 401) {
        setUser(null)
        return
      }
      if (!response.ok) throw new Error('Unable to load session')
      const payload = (await response.json()) as MeResponse
      setUser(payload.data)
    } finally {
      setAuthChecked(true)
    }
  }, [])

  useEffect(() => {
    fetch('/api/v1/health/live')
      .then((response) => {
        if (!response.ok) throw new Error('Backend unavailable')
        return response.json() as Promise<LiveStatus>
      })
      .then((data) => setBackendStatus(data.status))
      .catch(() => setBackendStatus('error'))

    void loadMe()
  }, [loadMe])

  const login = () => {
    window.location.assign('/api/v1/auth/login?next_url=/')
  }

  const logout = async () => {
    const csrfResponse = await fetch('/api/v1/auth/csrf', { credentials: 'same-origin' })
    if (!csrfResponse.ok) return
    const csrfPayload = (await csrfResponse.json()) as { data: { csrf_token: string } }
    const response = await fetch('/api/v1/auth/logout', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRF-Token': csrfPayload.data.csrf_token },
    })
    if (response.ok) setUser(null)
  }

  return (
    <main className="shell">
      <section className="card">
        <div className="brand">NambaDrive</div>
        <h1>Secure corporate file server</h1>
        <p>Secure organization and resource administration.</p>
        <dl>
          <div>
            <dt>Frontend</dt>
            <dd>ok</dd>
          </div>
          <div>
            <dt>Backend</dt>
            <dd>{backendStatus}</dd>
          </div>
          <div>
            <dt>Identity</dt>
            <dd>{!authChecked ? 'checking' : user ? 'authenticated' : 'anonymous'}</dd>
          </div>
        </dl>

        {user ? (
          <div className="authBox">
            <OrganizationAdmin />
            <ResourceAdmin />
            <strong>{user.display_name}</strong>
            <span>{user.email ?? user.username}</span>
            <button type="button" onClick={() => void logout()}>
              Выйти
            </button>
          </div>
        ) : (
          <div className="authBox">
            <span>Вход выполняется через Authentik. MFA остаётся на стороне Authentik.</span>
            <button type="button" onClick={login} disabled={!authChecked}>
              Войти через Authentik
            </button>
          </div>
        )}

        <p className="muted">
          OIDC tokens do not live in browser storage. NambaDrive uses its own server-side session.
        </p>
      </section>
    </main>
  )
}
