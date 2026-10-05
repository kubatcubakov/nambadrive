import { useEffect, useState } from 'react'
type Notice={id:string;message:string;created_at:string;read_at:string|null;resource_id:string|null}
async function api(path:string,method='GET',body?:object){
  const headers:Record<string,string>={'Content-Type':'application/json'}
  if(method!=='GET'){
    const response=await fetch('/api/v1/auth/csrf');if(!response.ok)throw new Error('Войдите повторно')
    headers['X-CSRF-Token']=(await response.json()).data.csrf_token as string
  }
  const response=await fetch('/api/v1/notifications'+path,{method,headers,body:body?JSON.stringify(body):undefined})
  if(!response.ok)throw new Error('Уведомления недоступны')
  return (await response.json()).data
}
export function Notifications(){
  const [rows,setRows]=useState<Notice[]>([])
  const [email,setEmail]=useState(true)
  const [status,setStatus]=useState('')
  useEffect(()=>{
    let active=true
    Promise.all([api(''),api('/preferences')]).then(([list,pref])=>{if(active){setRows(list as Notice[]);setEmail(pref.email_enabled as boolean)}}).catch(()=>{if(active)setStatus('Уведомления недоступны')})
    return ()=>{active=false}
  },[])
  async function run(action:()=>Promise<void>){try{setStatus('');await action()}catch(error){setStatus(error instanceof Error?error.message:'Ошибка')}}
  return <section><h2>Уведомления</h2>
    <label><input type="checkbox" checked={email} onChange={e=>{const enabled=e.target.checked;void run(async()=>{await api('/preferences','PUT',{email_enabled:enabled});setEmail(enabled)})}}/> Получать уведомления по email</label>
    <button onClick={()=>void run(async()=>setRows(await api('') as Notice[]))}>Обновить уведомления</button>
    {!rows.length&&<p>Пока нет уведомлений</p>}
    <ul>{rows.map(row=><li key={row.id}><p>{row.message}</p><time>{new Date(row.created_at).toLocaleString()}</time>{row.resource_id&&<a href={'/?document='+encodeURIComponent(row.resource_id)}>Открыть документ</a>}{!row.read_at&&<button onClick={()=>void run(async()=>{await api('/'+row.id+'/read','POST');setRows(await api('') as Notice[])})}>Прочитано</button>}</li>)}</ul>
    <p role="status">{status}</p>
  </section>
}
