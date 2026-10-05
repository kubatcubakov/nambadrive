import { useEffect, useState } from 'react'

type Version = { id:string; number:number; size:number; sha256:string; created_at:string; is_current:boolean }
export function Versions({documentId, canRestore}:{documentId:string;canRestore:boolean}) {
  const [versions,setVersions]=useState<Version[]>([])
  const [status,setStatus]=useState('')
  async function reload() {
    const response=await fetch(`/api/v1/documents/${documentId}/versions`)
    if(!response.ok) throw new Error('История версий недоступна')
    setVersions((await response.json()).data as Version[])
  }
  useEffect(()=>{
    let active=true
    fetch(`/api/v1/documents/${documentId}/versions`).then(async r=>{
      if(!r.ok) throw new Error('История недоступна')
      const rows=(await r.json()).data as Version[]
      if(active) setVersions(rows)
    }).catch(()=>{if(active)setStatus('История недоступна')})
    return ()=>{active=false}
  },[documentId])
  async function restore(version:Version) {
    try {
      const csrf=await fetch('/api/v1/auth/csrf')
      if(!csrf.ok) throw new Error('Войдите повторно')
      const response=await fetch(`/api/v1/documents/${documentId}/versions/${version.id}/restore`,{
        method:'POST',headers:{'X-CSRF-Token':(await csrf.json()).data.csrf_token as string},
      })
      if(!response.ok) throw new Error('Восстановление отклонено')
      await reload();setStatus('Создана новая версия из выбранной')
    } catch(error) {setStatus(error instanceof Error ? error.message : 'Ошибка')}
  }
  return <section><h4>История версий</h4><p role="status">{status}</p><ul>{versions.map(version=><li key={version.id}>
    Версия {version.number} {version.is_current?'(текущая)':''} · {version.size.toLocaleString()} байт · {new Date(version.created_at).toLocaleString()}
    <details><summary>Контрольная сумма</summary><code>{version.sha256}</code></details>
    {canRestore && !version.is_current && <button onClick={()=>void restore(version)}>Восстановить как новую версию</button>}
  </li>)}</ul></section>
}
