import { useCallback, useEffect, useState } from 'react'

type Department = { id: string; name: string; company_id: string; parent_id: string | null }
type Person = { id: string; display_name: string; enabled: boolean }
type Org = { companies: { id: string; name: string }[]; departments: Department[]; department_memberships: {user_id:string;department_id:string;kind:string}[]; department_managers: {user_id:string;department_id:string;revoked_at:string|null;valid_until:string|null}[] }
export function OrganizationAdmin() {
  const [org, setOrg] = useState<Org | null>(null)
  const [people, setPeople] = useState<Person[]>([])
  const [message, setMessage] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [name, setName] = useState('')
  const [company, setCompany] = useState('')
  const [parent, setParent] = useState('')
  const [department, setDepartment] = useState('')
  const [user, setUser] = useState('')
  const [kind, setKind] = useState('SECONDARY')
  const [expiry, setExpiry] = useState('')
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState('members')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => {
    const response = await fetch('/api/v1/admin/organization')
    if (!response.ok) throw new Error('Не удалось загрузить организацию. Проверьте права.')
    setOrg(((await response.json()) as { data: Org }).data)
  }, [])
  useEffect(() => { let active=true; void load().catch(error=>{if(active)setMessage(error.message)}); fetch('/api/v1/identity').then(async r=>{if(r.ok){const data=await r.json();if(active)setPeople(data.data.users)}}).catch(()=>{});return()=>{active=false} }, [load])
  async function save(path: string, method: string, body?: object) {
    setBusy(true); setMessage('')
    try {
      const csrf = await fetch('/api/v1/auth/csrf')
      if (!csrf.ok) throw new Error('Войдите повторно')
      const token = ((await csrf.json()) as { data: { csrf_token: string } }).data.csrf_token
      const response = await fetch('/api/v1/admin/organization/' + path, {
        method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
        body: body ? JSON.stringify(body) : undefined,
      })
      if (!response.ok) throw new Error('Изменение отклонено. Проверьте данные, срок и права.')
      await load(); setMessage('Изменения сохранены')
    } catch(error) {setMessage(error instanceof Error ? error.message : 'Операция не выполнена')}
    finally {setBusy(false)}
  }
  const companyId=company || org?.companies[0]?.id || ''
  const departments=org?.departments.filter(d=>d.company_id===companyId) ?? []
  const selected=departments.find(d=>d.id===department)
  const personName=(id:string)=>people.find(p=>p.id===id)?.display_name ?? id
  const memberships=(org?.department_memberships ?? []).filter(m=>m.department_id===department && personName(m.user_id).toLowerCase().includes(query.toLowerCase()))
  const managers=(org?.department_managers ?? []).filter(m=>m.department_id===department && !m.revoked_at)
  const renderTree=(parentId:string|null,visited=new Set<string>()):React.ReactNode => departments.filter(d=>d.parent_id===parentId && !visited.has(d.id)).map(d=><li key={d.id}><button aria-current={department===d.id?'page':undefined} onClick={()=>setDepartment(d.id)}>▰ {d.name}</button><ul>{renderTree(d.id,new Set([...visited,d.id]))}</ul></li>)
  return <section className="organization">
    <div className="section-heading"><h2>Организация</h2><label>Компания <select value={companyId} onChange={e=>{setCompany(e.target.value);setDepartment('');setParent('')}}><option value="">Выберите компанию</option>{org?.companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><button onClick={()=>void load().catch(error=>setMessage(error.message))}>Обновить</button></div>
    <p role="status">{message}</p>
    {!org && <p>Загрузка организации…</p>}
    {org && <div className="organization-layout"><aside className="organization-tree"><h3>Отделы</h3><ul>{renderTree(null)}</ul>{!departments.length && <p className="muted">Создайте первый отдел</p>}</aside><div className="organization-content">
      <h3>{selected ? selected.name : 'Выберите отдел'}</h3>
      <nav className="tabs" aria-label="Организация отдела">{[['members','Участники'],['managers','Руководители'],['structure','Структура']].map(([key,label])=><button key={key} aria-current={tab===key?'page':undefined} onClick={()=>setTab(key)}>{label}</button>)}</nav>
      {tab==='members' && <><label className="people-search">Поиск участника <input placeholder="Имя сотрудника" value={query} onChange={e=>setQuery(e.target.value)}/></label><table className="people-table"><thead><tr><th>Сотрудник</th><th>Членство в отделе</th></tr></thead><tbody>{memberships.map(m=><tr key={m.user_id}><td>{personName(m.user_id)}</td><td>{m.kind==='PRIMARY'?'Основной отдел':'Дополнительный отдел'}</td></tr>)}</tbody></table>{selected && !memberships.length && <p className="empty-state">Участников пока нет или они не найдены</p>}</>}
      {tab==='managers' && <><p className="muted">Руководитель получает операционный доступ к отделу. Legal Hold и политики хранения сохраняются.</p><ul className="member-list">{managers.map(m=><li key={m.user_id}><strong>{personName(m.user_id)}</strong><span>{m.valid_until ? new Date(m.valid_until).toLocaleString('ru') : 'Без срока'}{m.valid_until && new Date(m.valid_until)<new Date() ? ' · Истёк' : ''}</span><button disabled={busy} onClick={()=>void save(`departments/${department}/managers/${m.user_id}`,'DELETE')}>Отозвать назначение</button></li>)}</ul></>}
      {tab!=='structure' && <form className="form-card" onSubmit={e=>{e.preventDefault();void save(`departments/${department}/assignments`,'PUT',{user_id:user,kind,valid_until:kind==='MANAGER' && expiry ? new Date(expiry).toISOString():null})}}><h3>Назначить участника</h3>{people.length ? <label>Сотрудник <select aria-label="Сотрудник" required value={user} onChange={e=>setUser(e.target.value)}><option value="">Выберите сотрудника</option>{people.filter(p=>p.enabled).map(p=><option key={p.id} value={p.id}>{p.display_name}</option>)}</select></label> : <label>Идентификатор сотрудника <input required value={user} onChange={e=>setUser(e.target.value)}/><small>Список сотрудников недоступен с вашими правами.</small></label>}<label>Тип назначения <select value={kind} onChange={e=>setKind(e.target.value)}><option value="PRIMARY">Основной отдел</option><option value="SECONDARY">Дополнительный отдел</option><option value="MANAGER">Руководитель отдела</option></select></label>{kind==='MANAGER' && <label>Действует до (необязательно) <input type="datetime-local" value={expiry} onChange={e=>setExpiry(e.target.value)}/></label>}<button className="primary" disabled={busy || !selected || !user}>Назначить</button><p className="muted">Членство в отделе само по себе не выдаёт права на документы.</p></form>}
      {tab==='structure' && <><form className="form-card" onSubmit={e=>{e.preventDefault();void save('departments','POST',{name:name.trim(),company_id:companyId,parent_id:parent || null})}}><h3>Новый отдел или подразделение</h3><label>Название отдела <input required maxLength={255} value={name} onChange={e=>setName(e.target.value)}/></label><label>Родительский отдел <select value={parent} onChange={e=>setParent(e.target.value)}><option value="">Отдел компании</option>{departments.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></label><button className="primary" disabled={busy || !companyId || !name.trim()}>Создать отдел</button></form><form className="form-card" onSubmit={e=>{e.preventDefault();void save('companies','POST',{name:companyName.trim()})}}><h3>Новая компания</h3><label>Название компании <input required maxLength={255} value={companyName} onChange={e=>setCompanyName(e.target.value)}/></label><button disabled={busy || !companyName.trim()}>Создать компанию</button></form></>}
    </div></div>}
  </section>
}
