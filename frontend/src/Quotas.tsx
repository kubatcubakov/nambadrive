import { useEffect, useState } from 'react'

type Usage={used_bytes:number;limit_bytes:number|null}
type Quota=Usage&{subject_type:string;subject_id:string}
type Project={id:string;name:string;company_id:string|null;enabled:boolean}
type Reservation={version_id:string;owner_id:string;size:number;created_at:string}
const gib=(bytes:number)=> (bytes/1024**3).toLocaleString(undefined,{maximumFractionDigits:3})
async function api(path:string,method='GET',body?:object){
  const headers:Record<string,string>={'Content-Type':'application/json'}
  if(method!=='GET'){
    const csrf=await fetch('/api/v1/auth/csrf');if(!csrf.ok)throw new Error('Войдите повторно')
    headers['X-CSRF-Token']=(await csrf.json()).data.csrf_token as string
  }
  const response=await fetch('/api/v1/quotas'+path,{method,headers,body:body?JSON.stringify(body):undefined})
  if(!response.ok)throw new Error('Квоты недоступны: проверьте права и параметры')
  return (await response.json()).data
}
export function Quotas(){
  const [usage,setUsage]=useState<Usage|null>(null)
  const [manage,setManage]=useState(false)
  const [quotas,setQuotas]=useState<Quota[]>([])
  const [projects,setProjects]=useState<Project[]>([])
  const [reservations,setReservations]=useState<Reservation[]>([])
  const [kind,setKind]=useState('USER')
  const [subject,setSubject]=useState('')
  const [limit,setLimit]=useState(10)
  const [reason,setReason]=useState('')
  const [company,setCompany]=useState('')
  const [name,setName]=useState('')
  const [status,setStatus]=useState('')
  useEffect(()=>{
    let active=true
    api('/me').then(data=>{if(active)setUsage(data as Usage)}).catch(()=>{if(active)setStatus('Квота недоступна')})
    api('/capabilities').then(async data=>{if(active)setManage(data.manage as boolean);if(data.manage){
      const [q,p,r]=await Promise.all([api(''),api('/projects'),api('/reservations')]);if(active){setQuotas(q as Quota[]);setProjects(p as Project[]);setReservations(r as Reservation[])}
    }}).catch(()=>{if(active)setStatus('Администрирование квот недоступно')})
    return ()=>{active=false}
  },[])
  async function run(action:()=>Promise<void>){try{setStatus('');await action()}catch(error){setStatus(error instanceof Error?error.message:'Ошибка')}}
  return <section><h2>Использование хранилища</h2>
    {usage&&<p>Ваши документы: {gib(usage.used_bytes)} GiB / {usage.limit_bytes===null?'без отдельного лимита':gib(usage.limit_bytes)+' GiB'}. Версии и корзина учитываются до очистки.</p>}
    <button onClick={()=>void run(async()=>setUsage(await api('/me') as Usage))}>Обновить использование</button>
    {manage&&<><h3>Квоты пользователя, отдела и проекта</h3>
      <form onSubmit={e=>{e.preventDefault();void run(async()=>{await api('','PUT',{subject_type:kind,subject_id:subject,limit_bytes:Math.floor(limit*1024**3),reason});setQuotas(await api('') as Quota[])})}}>
        <select aria-label="Область квоты" value={kind} onChange={e=>setKind(e.target.value)}><option value="USER">Пользователь</option><option value="DEPARTMENT">Отдел</option><option value="PROJECT">Проект</option></select>
        <label>UUID <input required value={subject} onChange={e=>setSubject(e.target.value)}/></label><label>Лимит GiB (0 блокирует новые записи) <input required type="number" min={0} max={1000000} step="0.001" value={limit} onChange={e=>setLimit(Number(e.target.value))}/></label>
        <label>Причина <input required maxLength={2000} value={reason} onChange={e=>setReason(e.target.value)}/></label><button>Сохранить квоту</button>
      </form>
      <ul>{quotas.map(row=><li key={row.subject_type+row.subject_id}>{row.subject_type} {row.subject_id}: {gib(row.used_bytes)} / {gib(row.limit_bytes??0)} GiB</li>)}</ul>
      <h3>Проекты</h3><form onSubmit={e=>{e.preventDefault();void run(async()=>{await api('/projects','POST',{company_id:company,name});setProjects(await api('/projects') as Project[])})}}><label>UUID компании <input required value={company} onChange={e=>setCompany(e.target.value)}/></label><label>Название <input required maxLength={200} value={name} onChange={e=>setName(e.target.value)}/></label><button>Создать проект</button></form>
      <ul>{projects.map(project=><li key={project.id}>{project.name} · {project.id} · {project.enabled?'Активен':'Требует сверки'}</li>)}</ul>
      <details><summary>Незавершённые записи: {reservations.length}</summary><p>Резервы учитываются в квоте до сверки с хранилищем; автоматического освобождения по таймеру нет.</p><ul>{reservations.map(row=><li key={row.version_id}>{row.version_id} · {gib(row.size)} GiB · {new Date(row.created_at).toLocaleString()}</li>)}</ul></details>
    </>}
    <p role="status">{status}</p>
  </section>
}
