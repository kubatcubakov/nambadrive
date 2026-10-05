import { useCallback, useEffect, useState } from 'react'
import { Shares } from './Shares'
import { RequestAccess } from './AccessRequests'
import { OfficeEditor } from './OfficeEditor'
import { Versions } from './Versions'
import { Upload } from './Upload'
import { Search } from './Search'

type Item = { id: string; name: string; resource_type: string; department_id: string }
type Detail = Item & { size: number; mime_type: string; owner_user_id: string; sha256: string; metadata: { description?: string; tags?: string[]; project_id?: string | null } }
async function api(path: string, method = 'GET', body?: object) {
  const headers: Record<string,string> = { 'Content-Type':'application/json' }
  if (method !== 'GET') {
    const csrf = await fetch('/api/v1/auth/csrf')
    if (!csrf.ok) throw new Error('Войдите повторно')
    headers['X-CSRF-Token'] = (await csrf.json()).data.csrf_token as string
  }
  const response = await fetch('/api/v1'+path, { method, headers, body: body ? JSON.stringify(body) : undefined })
  if (!response.ok) throw new Error('Операция недоступна: проверьте права и данные')
  return (await response.json()).data
}

export function Drive() {
  const [path, setPath] = useState<Item[]>([])
  const [rows, setRows] = useState<Item[]>([])
  const [trash, setTrash] = useState(false)
  const [selected, setSelected] = useState<Detail | null>(null)
  const [permissions, setPermissions] = useState<string[]>([])
  const [status, setStatus] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [newOfficeName, setNewOfficeName] = useState('')
  const [newOfficeFormat, setNewOfficeFormat] = useState('docx')
  const [preview, setPreview] = useState(false)
  const [rename, setRename] = useState('')
  const [description, setDescription] = useState('')
  const [tags, setTags] = useState('')
  const [project, setProject] = useState('')
  const [projects, setProjects] = useState<{id:string;name:string}[]>([])
  const [destination, setDestination] = useState<Item[]>([])
  const [targets, setTargets] = useState<Item[]>([])
  const [transfer, setTransfer] = useState<'move'|'copy'|null>(null)
  const parent = path.at(-1)
  const parentId = parent?.id
  async function reload() {
    setRows(await api(trash ? '/documents/trash' : '/resources'+(parentId ? '?parent_id='+parentId : '')) as Item[])
  }
  useEffect(() => {
    let active = true
    api(trash ? '/documents/trash' : '/resources'+(parentId ? '?parent_id='+parentId : ''))
      .then(data => { if (active) setRows(data as Item[]) })
      .catch(() => { if (active) setStatus('Не удалось загрузить папку') })
    return () => { active = false }
  }, [parentId, trash])
  async function run(action: () => Promise<void>) {
    try { setStatus(''); await action() } catch (error) { setStatus(error instanceof Error ? error.message : 'Ошибка') }
  }
  const loadDocument = useCallback(async (id: string) => {
    setPreview(false); setPermissions([])
    const detail = await api('/documents/'+id) as Detail
    const allowed = await Promise.all('PREVIEW DOWNLOAD RENAME MOVE COPY DELETE EDIT VIEW_VERSION_HISTORY RESTORE_VERSION UPLOAD_NEW_VERSION SHARE EXTERNAL_SHARE'.split(' ').map(async p => {
      const decision = await api(`/resources/${id}/permissions/${p}`) as { decision: string }
      return decision.decision === 'ALLOW' ? p : ''
    }))
    setSelected(detail); setPermissions(allowed); setRename(detail.name)
    setProject(detail.metadata.project_id ?? '')
    setProjects(allowed.includes('EDIT') ? await api('/quotas/projects-for/'+id) as {id:string;name:string}[] : [])
    setDescription(detail.metadata.description ?? ''); setTags((detail.metadata.tags ?? []).join(', '))
  }, [])
  useEffect(()=>{
    const id=new URLSearchParams(window.location.search).get('document')
    if(id) void loadDocument(id).catch(()=>setStatus('Документ по ссылке недоступен'))
  },[loadDocument])
  async function open(item: Item) {
    if (item.resource_type !== 'DOCUMENT') { setPath([...path,item]); setSelected(null); return }
    await loadDocument(item.id)
  }
  async function browseDestination(next: Item[]) {
    setDestination(next)
    const id = next.at(-1)?.id
    setTargets((await api('/resources'+(id ? '?parent_id='+id : '')) as Item[]).filter(r => r.resource_type !== 'DOCUMENT'))
  }
  return <section className="drive">
    <h2>Документы</h2>
    <Search onOpen={async hit=>{setTrash(false);await open(hit)}} />
    {editing && <OfficeEditor documentId={editing} onClose={() => setEditing(null)} />}
    <nav aria-label="Документы"><button onClick={() => {setTrash(false);setPath([]);setSelected(null)}}>Общие пространства</button><button onClick={() => {setTrash(true);setSelected(null)}}>Корзина</button><button onClick={() => void run(reload)}>Обновить</button></nav>
    {!trash && <nav aria-label="Путь">{path.map((item,index) => <button key={item.id} onClick={() => {setPath(path.slice(0,index+1));setSelected(null)}}>{item.name}</button>)}</nav>}
    <p role="status">{status}</p>
    <ul className="file-list">{rows.map(item => <li key={item.id}>
      {trash ? <><span>{item.name}</span><button onClick={() => void run(async () => {await api(`/documents/${item.id}/restore`,'POST'); await reload()})}>Восстановить</button></> : <button onClick={() => void run(() => open(item))}>{item.resource_type === 'DOCUMENT' ? '▤' : '▣'} {item.name}</button>}
    </li>)}</ul>
    {!rows.length && <p>Нет доступных документов</p>}
    {!trash && parent && <><Upload key={parent.id} parentId={parent.id} />
    <form onSubmit={e => {e.preventDefault();void run(async()=>{await api('/office/create','POST',{parent_id:parent.id,name:newOfficeName,format:newOfficeFormat});setStatus('Документ создан и ожидает антивирусной проверки');setNewOfficeName('')})}}>
      <label>Новый документ <input required value={newOfficeName} onChange={e=>setNewOfficeName(e.target.value)} /></label>
      <select aria-label="Формат нового документа" value={newOfficeFormat} onChange={e=>setNewOfficeFormat(e.target.value)}><option value="docx">Текст</option><option value="xlsx">Таблица</option><option value="pptx">Презентация</option></select><button>Создать</button>
    </form></>}
    {selected && !trash && <article>
      {permissions.includes('SHARE') && <Shares key={selected.id} documentId={selected.id} external={permissions.includes('EXTERNAL_SHARE')} />}
      <RequestAccess key={selected.id+'-request'} documentId={selected.id} />
      <h3>{selected.name}</h3><p>{selected.mime_type} · {selected.size.toLocaleString()} байт</p>
      <dl><dt>Владелец</dt><dd>{selected.owner_user_id}</dd><dt>Отдел</dt><dd>{selected.department_id}</dd></dl>
      {permissions.includes('EDIT') && /\.(docx|xlsx|pptx)$/i.test(selected.name) && <button onClick={()=>setEditing(selected.id)}>Открыть в редакторе</button>}
      {permissions.includes('PREVIEW') && <button onClick={() => setPreview(!preview)}>Предпросмотр</button>}
      {permissions.includes('DOWNLOAD') && <a href={`/api/v1/documents/${selected.id}/download`}>Скачать</a>}
      {preview && <img className="document-preview" src={`/api/v1/documents/${selected.id}/preview`} alt="Предпросмотр документа" onError={() => setStatus('Предпросмотр для этого файла недоступен')} />}
      {permissions.includes('RENAME') && <form onSubmit={e => {e.preventDefault(); void run(async () => {await api(`/documents/${selected.id}/rename`,'POST',{name:rename}); await reload();setSelected({...selected,name:rename})})}}><label>Имя <input value={rename} onChange={e=>setRename(e.target.value)} /></label><button>Переименовать</button></form>}
      {permissions.includes('EDIT') && <form onSubmit={e=>{e.preventDefault();void run(async()=>{await api(`/documents/${selected.id}/metadata`,'PUT',{...selected.metadata,project_id:project||null,description,tags:tags.split(',').map(t=>t.trim()).filter(Boolean)});setStatus('Описание сохранено')})}}><label>Проект <select value={project} onChange={e=>setProject(e.target.value)}><option value="">Без проекта</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label>Описание <textarea value={description} onChange={e=>setDescription(e.target.value)} /></label><label>Теги через запятую <input value={tags} onChange={e=>setTags(e.target.value)} /></label><button>Сохранить</button></form>}
      {(['move','copy'] as const).map(action=>permissions.includes(action.toUpperCase()) && <button key={action} onClick={()=>void run(async()=>{setTransfer(action);await browseDestination([])})}>{action==='move'?'Переместить':'Копировать'}</button>)}
      {permissions.includes('UPLOAD_NEW_VERSION') && <Upload documentId={selected.id} />}
      {permissions.includes('VIEW_VERSION_HISTORY') && <Versions key={selected.id} documentId={selected.id} canRestore={permissions.includes('RESTORE_VERSION')} />}
      {permissions.includes('DELETE') && <button onClick={()=>void run(async()=>{await api('/documents/'+selected.id,'DELETE');setSelected(null);await reload()})}>В корзину</button>}
    </article>}
    {transfer && selected && <section aria-label="Выбор папки назначения">
      <h3>Папка назначения</h3><button onClick={()=>void run(()=>browseDestination(destination.slice(0,-1)))}>Назад</button>
      <p>{destination.map(item=>item.name).join(' / ') || 'Пространства'}</p>
      {targets.map(item=><button key={item.id} onClick={()=>void run(()=>browseDestination([...destination,item]))}>{item.name}</button>)}
      <button disabled={!destination.length} onClick={()=>void run(async()=>{await api(`/documents/${selected.id}/${transfer}`,'POST',{parent_id:destination.at(-1)?.id});setTransfer(null);setSelected(null);await reload()})}>Выбрать эту папку</button><button onClick={()=>setTransfer(null)}>Отмена</button>
    </section>}
  </section>
}
