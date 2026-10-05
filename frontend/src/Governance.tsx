import { useEffect, useState } from 'react'

type Policy={id:string;name:string;resource_id:string|null;document_type:string|null;days:number;revoked_at:string|null}
type HoldEvent={id:string;enabled:boolean;reason:string;created_at:string}
type State={legal_hold:boolean;retention_until:string|null;purged_at:string|null;hold_history:HoldEvent[]}
async function api(path:string,method='GET',body?:object) {
  const headers:Record<string,string>={'Content-Type':'application/json'}
  if(method!=='GET') {
    const csrf=await fetch('/api/v1/auth/csrf')
    if(!csrf.ok)throw new Error('Войдите повторно')
    headers['X-CSRF-Token']=(await csrf.json()).data.csrf_token as string
  }
  const response=await fetch('/api/v1/admin/governance'+path,{method,headers,body:body?JSON.stringify(body):undefined})
  if(!response.ok)throw new Error('Изменение политики недоступно: проверьте права, область и срок')
  return (await response.json()).data
}
export function Governance() {
  const [capabilities,setCapabilities]=useState<Record<string,boolean>>({})
  const [policies,setPolicies]=useState<Policy[]>([])
  const [resource,setResource]=useState('')
  const [state,setState]=useState<State|null>(null)
  const [name,setName]=useState('')
  const [type,setType]=useState('')
  const [days,setDays]=useState(1826)
  const [until,setUntil]=useState('')
  const [reason,setReason]=useState('')
  const [status,setStatus]=useState('')
  useEffect(()=>{
    let active=true
    api('/capabilities').then(async data=>{
      if(active)setCapabilities(data as Record<string,boolean>)
      if(data.MANAGE_RETENTION){const rows=await api('/policies');if(active)setPolicies(rows as Policy[])}
    }).catch(()=>{if(active)setStatus('Администрирование политик недоступно')})
    return ()=>{active=false}
  },[])
  async function run(action:()=>Promise<void>){try{setStatus('');await action();setStatus('Сохранено')}catch(error){setStatus(error instanceof Error?error.message:'Ошибка')}}
  async function load(){setState(await api('/resources/'+resource) as State)}
  if(!capabilities.MANAGE_RETENTION && !capabilities.MANAGE_LEGAL_HOLD)return null
  return <section><h2>Хранение и Legal Hold</h2>
    <label>Причина изменения <input required maxLength={2000} value={reason} onChange={e=>setReason(e.target.value)} /></label>
    <label>UUID пространства, папки или документа <input value={resource} onChange={e=>{setResource(e.target.value);setState(null)}} /></label>
    <p>Пустая область при создании политики означает все документы. Уже назначенный срок хранения версии не сокращается.</p>
    {capabilities.MANAGE_RETENTION && <>
      <form onSubmit={e=>{e.preventDefault();void run(async()=>{await api('/policies','POST',{name,resource_id:resource||null,document_type:type||null,days,reason});setPolicies(await api('/policies') as Policy[])})}}>
        <label>Название политики <input required maxLength={200} value={name} onChange={e=>setName(e.target.value)} /></label>
        <label>Формат <select value={type} onChange={e=>setType(e.target.value)}><option value="">Все</option>{'docx xlsx pptx pdf zip jpg png dwg psd txt csv json xml'.split(' ').map(t=><option key={t}>{t}</option>)}</select></label>
        <label>Дней с создания версии <input required type="number" min={1} max={36500} value={days} onChange={e=>setDays(Number(e.target.value))} /></label><button disabled={!reason.trim()}>Создать политику</button>
      </form>
      <ul>{policies.map(policy=><li key={policy.id}>{policy.name} · {policy.days} дней · {policy.document_type??'все форматы'} · {policy.resource_id??'все документы'} {policy.revoked_at?'Отменена для будущих версий':<button disabled={!reason.trim()} onClick={()=>void run(async()=>{await api('/policies/'+policy.id+'/revoke','POST',{reason});setPolicies(await api('/policies') as Policy[])})}>Отменить для будущих версий</button>}</li>)}</ul>
      <label>Продлить хранение области до <input type="datetime-local" value={until} onChange={e=>setUntil(e.target.value)} /></label><button disabled={!resource||!until||!reason.trim()} onClick={()=>void run(async()=>{await api(`/resources/${resource}/retention`,'PUT',{until:new Date(until).toISOString(),reason})})}>Продлить</button>
    </>}
    {capabilities.MANAGE_LEGAL_HOLD && <><button disabled={!resource} onClick={()=>void run(load)}>Показать состояние и историю</button>
      {state && <><p>Legal Hold: {state.legal_hold?'установлен':'не установлен'} · Хранение до: {state.retention_until??'не задано'} · {state.purged_at?'Данные уже очищены':''}</p>
        <button disabled={!reason.trim()||!!state.purged_at} onClick={()=>void run(async()=>{await api(`/resources/${resource}/hold`,'PUT',{enabled:!state.legal_hold,reason});await load()})}>{state.legal_hold?'Снять Legal Hold':'Установить Legal Hold'}</button>
        <ul>{state.hold_history.map(event=><li key={event.id}>{new Date(event.created_at).toLocaleString()} · {event.enabled?'Установлен':'Снят'} · {event.reason}</li>)}</ul>
      </>}
    </>}
    <p role="status">{status}</p>
  </section>
}
