import { useEffect, useState } from 'react'

declare global {
  interface Window { DocsAPI?: { DocEditor: new (id:string,config:Record<string,unknown>) => {destroyEditor:()=>void} } }
}
export function OfficeEditor({documentId,onClose}:{documentId:string;onClose:()=>void}) {
  const [status,setStatus]=useState('Подключение редактора…')
  useEffect(()=>{
    let disposed=false
    let editor:{destroyEditor:()=>void}|undefined
    let expiryTimer:ReturnType<typeof setTimeout>|undefined
    const target='office-editor-'+documentId
    async function start() {
      const csrf=await fetch('/api/v1/auth/csrf')
      if(!csrf.ok) throw new Error('Войдите повторно')
      const response=await fetch(`/api/v1/office/${documentId}/session`,{method:'POST',headers:{'X-CSRF-Token':(await csrf.json()).data.csrf_token as string}})
      if(!response.ok) throw new Error('Редактор недоступен. Проверьте права или дождитесь антивирусной проверки сохранения.')
      const data=(await response.json()).data as {config:Record<string,unknown>;script_url:string;expires_at:string}
      if(!window.DocsAPI) await new Promise<void>((resolve,reject)=>{
        const script=document.createElement('script');script.src=data.script_url;script.async=true
        script.onload=()=>resolve();script.onerror=()=>reject(new Error('Сервер редактора недоступен'))
        document.head.appendChild(script)
      })
      if(disposed) return
      if(!window.DocsAPI) throw new Error('Редактор не загрузился')
      editor=new window.DocsAPI.DocEditor(target,{...data.config,width:'100%',height:'650px'})
      setStatus('Изменения сохраняются как новые версии и проходят антивирусную проверку.')
      expiryTimer=setTimeout(()=>{editor?.destroyEditor();setStatus('Сессия редактирования истекла. Закройте и откройте документ заново.')},Math.max(0,new Date(data.expires_at).getTime()-Date.now()))
    }
    void start().catch(error=>{if(!disposed)setStatus(error instanceof Error?error.message:'Ошибка редактора')})
    return ()=>{disposed=true;if(expiryTimer)clearTimeout(expiryTimer);editor?.destroyEditor()}
  },[documentId])
  return <section><h3>Редактор</h3><p role="status">{status}</p><button onClick={onClose}>Закрыть редактор</button><div id={'office-editor-'+documentId} /></section>
}
