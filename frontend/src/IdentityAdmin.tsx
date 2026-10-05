import { useEffect, useState } from 'react'

type Status={global_owner_id:string|null;pending_transfers:{resource_id:string;previous_owner_id:string}[];users:{id:string;display_name:string;enabled:boolean}[]}
async function api(path='',method='GET',body?:object){
  const headers:Record<string,string>={'Content-Type':'application/json'}
  if(method!=='GET'){
    const csrf=await fetch('/api/v1/auth/csrf');if(!csrf.ok)throw new Error('Войдите повторно')
    headers['X-CSRF-Token']=(await csrf.json()).data.csrf_token as string
  }
  const response=await fetch('/api/v1/identity'+path,{method,headers,body:body?JSON.stringify(body):undefined})
  if(!response.ok)throw new Error('Не удалось выполнить операцию')
  return (await response.json()).data
}
export function IdentityAdmin(){
  const [data,setData]=useState<Status|null>(null)
  const [owner,setOwner]=useState('')
  const [reason,setReason]=useState('')
  const [error,setError]=useState('')
  useEffect(()=>{let active=true;api().then((s:Status)=>{if(active){setData(s);setOwner(s.global_owner_id??'')}}).catch(()=>{});return()=>{active=false}},[])
  async function run(action:()=>Promise<void>){try{await action();setData(await api() as Status);setError('')}catch{setError('Операция не выполнена. Проверьте права и доступность аудита.')}}
  if(!data)return null
  return <section><h2>Жизненный цикл пользователей</h2>
    <p>Отключение отзывает сеансы и персональные права. Владение передаётся ответственному отдела, затем владельцу пространства, затем выбранному резервному владельцу.</p>
    <form onSubmit={e=>{e.preventDefault();void run(async()=>{await api('/policy','PUT',{global_owner_id:owner,reason})})}}>
      <label>Резервный владелец <select required value={owner} onChange={e=>setOwner(e.target.value)}><option value="">Выберите пользователя</option>{data.users.filter(u=>u.enabled).map(u=><option key={u.id} value={u.id}>{u.display_name}</option>)}</select></label>
      <label>Причина <input required maxLength={2000} value={reason} onChange={e=>setReason(e.target.value)}/></label><button>Сохранить</button>
    </form>
    <p>Ожидают передачи: {data.pending_transfers.length}. Отключённые пользователи не получают доступ во время ожидания.</p>
    <ul>{data.users.map(u=><li key={u.id}>{u.display_name} · {u.enabled?'Активен':'Отключён'} {u.enabled&&<button onClick={()=>{if(window.confirm('Отключить '+u.display_name+' и отозвать доступ?'))void run(async()=>{await api('/'+u.id+'/disable','POST')})}}>Отключить</button>}</li>)}</ul><p role="status">{error}</p>
  </section>
}
