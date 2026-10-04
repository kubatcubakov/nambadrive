import { useEffect, useState } from 'react'

type Share = { id: string; expires_at: string; revoked_at: string | null; views: number; max_views: number | null; allow_download: boolean; password_protected: boolean }
async function api(path: string, method = 'GET', body?: object) {
  const headers: Record<string,string> = {'Content-Type':'application/json'}
  if (method !== 'GET') {
    const csrf = await fetch('/api/v1/auth/csrf')
    if (!csrf.ok) throw new Error('Войдите повторно')
    headers['X-CSRF-Token'] = (await csrf.json()).data.csrf_token as string
  }
  const response = await fetch('/api/v1/shares'+path,{method,headers,body:body ? JSON.stringify(body) : undefined})
  if (!response.ok) throw new Error('Ссылка недоступна: проверьте права, классификацию и параметры')
  return (await response.json()).data
}

export function Shares({ documentId, external }: { documentId: string; external: boolean }) {
  const [rows,setRows] = useState<Share[]>([])
  const [link,setLink] = useState('')
  const [status,setStatus] = useState('')
  const [days,setDays] = useState(7)
  const [password,setPassword] = useState('')
  const [maxViews,setMaxViews] = useState('')
  const [download,setDownload] = useState(false)
  useEffect(()=>{
    let active=true
    api('/documents/'+documentId).then(data=>{if(active)setRows(data as Share[])}).catch(()=>{if(active)setStatus('Список ссылок недоступен')})
    return ()=>{active=false}
  },[documentId])
  async function run(action:()=>Promise<void>) {
    try {setStatus('');await action()} catch(error) {setStatus(error instanceof Error ? error.message : 'Ошибка')}
  }
  return <section aria-label="Поделиться документом">
    <h4>Поделиться</h4><button onClick={()=>void run(async()=>{const data=await api('/internal/'+documentId,'POST');setLink(new URL(data.path as string,window.location.origin).href)})}>Внутренняя ссылка</button>
    {external && <form onSubmit={event=>{event.preventDefault();void run(async()=>{
      const data=await api('/documents/'+documentId,'POST',{days,password:password || null,max_views:maxViews ? Number(maxViews) : null,allow_view:true,allow_download:download})
      setLink(new URL(data.path as string,window.location.origin).href);setPassword('');setRows(await api('/documents/'+documentId) as Share[])
    })}}>
      <label>Срок, дней <input type="number" min={1} max={30} value={days} onChange={e=>setDays(Number(e.target.value))} /></label>
      <label>Пароль (необязательно, от 12 символов) <input type="password" autoComplete="new-password" minLength={12} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} /></label>
      <label>Максимум обращений <input type="number" min={1} max={1000000} value={maxViews} onChange={e=>setMaxViews(e.target.value)} /></label>
      <label><input type="checkbox" checked={download} onChange={e=>setDownload(e.target.checked)} />Разрешить скачивание</label><button>Создать внешнюю ссылку</button>
    </form>}
    {link && <label>Сохраните ссылку — секрет повторно не показывается <input readOnly value={link} onFocus={e=>e.target.select()} /></label>}
    <p role="status">{status}</p><ul>{rows.map(row=><li key={row.id}>До {new Date(row.expires_at).toLocaleString()} · {row.views}/{row.max_views ?? '∞'} обращений · {row.password_protected ? 'с паролем' : 'без пароля'} · {row.allow_download ? 'скачивание разрешено' : 'просмотр'} {row.revoked_at ? 'Отозвана' : <button onClick={()=>void run(async()=>{await api(`/documents/${documentId}/${row.id}`,'DELETE');setRows(await api('/documents/'+documentId) as Share[])})}>Отозвать</button>}</li>)}</ul>
  </section>
}

export function ExternalShare() {
  const [token] = useState(()=>window.location.hash.slice(1))
  const [password,setPassword] = useState('')
  const [page,setPage] = useState(0)
  const [preview,setPreview] = useState('')
  const [status,setStatus] = useState('')
  const [busy,setBusy] = useState(false)
  useEffect(()=>{window.history.replaceState(null,'','/share')},[])
  useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview)},[preview])
  async function access(action:'preview'|'download') {
    setBusy(true);setStatus('')
    try {
      const response=await fetch('/api/v1/shares/access',{method:'POST',credentials:'omit',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,password:password || null,action,page})})
      if(!response.ok) throw new Error(response.status===429 ? 'Слишком много попыток. Повторите через минуту.' : 'Ссылка, пароль или выбранное действие недоступны')
      const url=URL.createObjectURL(await response.blob())
      if(action==='preview') setPreview(url)
      else {
        const disposition=response.headers.get('Content-Disposition') ?? ''
        const filename=disposition.split("filename*=UTF-8''")[1]
        const anchor=document.createElement('a');anchor.href=url;anchor.download=filename ? decodeURIComponent(filename) : 'document'
        anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
      }
    } catch(error) {setStatus(error instanceof Error ? error.message : 'Ошибка')}
    finally {setBusy(false)}
  }
  return <main className="shell"><section className="card"><h1>NambaDrive — документ по ссылке</h1>
    <label>Пароль, если установлен <input type="password" autoComplete="off" maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} /></label>
    <label>Страница PDF <input type="number" min={1} max={10001} value={page+1} onChange={e=>setPage(Number(e.target.value)-1)} /></label>
    <p>Каждый просмотр страницы или скачивание расходует одно обращение, если задан лимит.</p>
    <button disabled={busy || !token} onClick={()=>void access('preview')}>Просмотр</button><button disabled={busy || !token} onClick={()=>void access('download')}>Скачать, если разрешено</button>
    <p role="status">{token ? status : 'Откройте полную ссылку, полученную от отправителя'}</p>
    {preview && <img className="document-preview" src={preview} alt="Документ по внешней ссылке" />}
  </section></main>
}
