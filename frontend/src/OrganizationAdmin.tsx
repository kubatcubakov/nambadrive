import { useState } from 'react'

type Org = { companies: { id: string; name: string }[]; departments: { id: string; name: string; parent_id: string | null }[] }

export function OrganizationAdmin() {
  const [org, setOrg] = useState<Org | null>(null)
  const [message, setMessage] = useState('')
  const [name, setName] = useState('')
  const [company, setCompany] = useState('')
  const [parent, setParent] = useState('')
  const [department, setDepartment] = useState('')
  const [user, setUser] = useState('')
  const [kind, setKind] = useState('SECONDARY')
  const [expiry, setExpiry] = useState('')
  async function load() {
    const response = await fetch('/api/v1/admin/organization')
    if (!response.ok) { setMessage('Organization administration access required'); return }
    setOrg(((await response.json()) as { data: Org }).data)
    setMessage('')
  }
  async function save(path: string, method: string, body?: object) {
    const csrf = await fetch('/api/v1/auth/csrf')
    if (!csrf.ok) { setMessage('Session unavailable'); return }
    const token = ((await csrf.json()) as { data: { csrf_token: string } }).data.csrf_token
    const response = await fetch('/api/v1/admin/organization/' + path, {
      method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!response.ok) { setMessage('Change rejected. Check identifiers, expiry and permissions.'); return }
    await load()
  }
  return <section>
    <h2>Organization administration</h2>
    <button onClick={() => void load()}>Load organization</button>
    <p role="status">{message}</p>
    {org && <>
      <ul>{org.companies.map(c => <li key={c.id}>{c.name} — {c.id}</li>)}</ul>
      <ul>{org.departments.map(d => <li key={d.id}>{d.name} — {d.id} {d.parent_id && '(section)'}</li>)}</ul>
      <label>Name <input value={name} onChange={e => setName(e.target.value)} /></label>
      <button onClick={() => void save('companies', 'POST', { name })}>Create company</button>
      <label>Company UUID <input value={company} onChange={e => setCompany(e.target.value)} /></label>
      <label>Parent department UUID (optional) <input value={parent} onChange={e => setParent(e.target.value)} /></label>
      <button onClick={() => void save('departments', 'POST', { name, company_id: company, parent_id: parent || null })}>Create department / section</button>
      <label>Department UUID <input value={department} onChange={e => setDepartment(e.target.value)} /></label>
      <label>User UUID <input value={user} onChange={e => setUser(e.target.value)} /></label>
      <label>Assignment <select value={kind} onChange={e => setKind(e.target.value)}><option>PRIMARY</option><option>SECONDARY</option><option>MANAGER</option></select></label>
      <label>Manager expiry (optional) <input type="datetime-local" value={expiry} onChange={e => setExpiry(e.target.value)} /></label>
      <button onClick={() => void save(`departments/${department}/assignments`, 'PUT', { user_id: user, kind, valid_until: expiry ? new Date(expiry).toISOString() : null })}>Assign</button>
      <button onClick={() => void save(`departments/${department}/managers/${user}`, 'DELETE')}>Revoke manager</button>
    </>}
  </section>
}
