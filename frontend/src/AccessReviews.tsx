import { useEffect, useState } from 'react'
type Review={id:string;resource_id:string;quarter:string;due_at:string;completed_at:string|null;overdue:boolean}
type Item={id:string;snapshot:Record<string,unknown>;decision:string;reason:string|null;can_revoke:boolean}
type Detail={id:string;completed_at:string|null;items:Item[]}
async function api(path:string,method='GET',body?:object){
  const headers:Record<string,string>={'Content-Type':'application/json'}
  if(method!=='GET'){
    const csrf=await fetch('/api/v1/auth/csrf');if(!csrf.ok)throw new Error('Войдите повторно')
    headers['X-CSRF-Token']=(await csrf.json()).data.csrf_token as string
  }
  const response=await fetch('/api/v1/access-reviews'+path,{method,headers,body:body?JSON.stringify(body):undefined})
  if(!response.ok)throw new Error(response.status===409?'Права изменились или не все пункты рассмотрены. Обновите снимок.':'Пересмотр недоступен: проверьте права')
  return (await response.json()).data
}
export function AccessReviews(){
  const [reviews,setReviews]=useState<Review[]>([])
  const [detail,setDetail]=useState<Detail|null>(null)
  const [reason,setReason]=useState('')
  const [status,setStatus]=useState('')
  useEffect(()=>{let active=true;api('').then(data=>{if(active)setReviews(data as Review[])}).catch(()=>{if(active)setStatus('Пересмотры недоступны')});return()=>{active=false}},[])
  async function run(action:()=>Promise<void>){try{setStatus('');await action()}catch(error){setStatus(error instanceof Error?error.message:'Ошибка')}}
  return <section><h2>Квартальный пересмотр доступа</h2><p>Просрочка не отзывает права автоматически. Рассмотрите назначения и унаследованные права; изменения фиксируются в аудите.</p>
    <button onClick={()=>void run(async()=>setReviews(await api('') as Review[]))}>Обновить список</button>
    {!reviews.length&&<p>Нет доступных заданий пересмотра</p>}
    <ul>{reviews.map(row=><li key={row.id}><button onClick={()=>void run(async()=>{setDetail(await api('/'+row.id) as Detail);setReason('')})}>{row.quarter} · {row.resource_id}</button> {row.completed_at?'Завершён':row.overdue?'Просрочен':'Ожидает решения'} · до {new Date(row.due_at).toLocaleDateString()}</li>)}</ul>
    {detail&&<div><h3>Назначения доступа</h3><p>Это снимок назначений. Фактический доступ также зависит от DENY, политик, классификации и состояния пользователя.</p>
      {!detail.completed_at&&<><label>Причина решения <input required maxLength={2000} value={reason} onChange={e=>setReason(e.target.value)}/></label><button onClick={()=>void run(async()=>{await api('/'+detail.id+'/refresh','POST');setDetail(await api('/'+detail.id) as Detail)})}>Обновить снимок прав</button></>}
      <ul>{detail.items.map(item=><li key={item.id}><strong>{String(item.snapshot.kind)}</strong> · {String(item.snapshot.principal_id??item.snapshot.user_id??'')} · {String(item.snapshot.permission_id??item.snapshot.permission??item.snapshot.role??'Менеджер')} · {String(item.snapshot.effect??'Системное/ролевое назначение')}<p>Решение: {item.decision} {item.reason}</p><details><summary>Источник и параметры</summary><pre>{JSON.stringify(item.snapshot,null,2)}</pre></details>
        {!detail.completed_at&&item.decision==='PENDING'&&<><button disabled={!reason.trim()} onClick={()=>void run(async()=>{await api('/'+detail.id+'/items/'+item.id,'POST',{decision:'KEEP',reason});setDetail(await api('/'+detail.id) as Detail)})}>Сохранить</button>{item.can_revoke?<button disabled={!reason.trim()} onClick={()=>void run(async()=>{await api('/'+detail.id+'/items/'+item.id,'POST',{decision:'REVOKE',reason});setDetail(await api('/'+detail.id) as Detail)})}>Отозвать назначение</button>:<span>Отзыв выполняется уполномоченным администратором источника назначения.</span>}</>}
      </li>)}</ul>
      {!detail.completed_at&&<button onClick={()=>void run(async()=>{await api('/'+detail.id+'/complete','POST');setDetail(await api('/'+detail.id) as Detail);setReviews(await api('') as Review[])})}>Завершить пересмотр</button>}
    </div>}
    <p role="status">{status}</p>
  </section>
}
