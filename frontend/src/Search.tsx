import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from './Icons'
type Hit = { id: string; name: string; resource_type: string; department_id: string; snippet: string }
export function Search({ onOpen, host }: { onOpen: (hit: Hit) => Promise<void>; host?: HTMLElement | null }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Hit[]>([])
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  async function search() {
    setBusy(true); setResults([]); setStatus('')
    try {
      const response = await fetch('/api/v1/search?q='+encodeURIComponent(query))
      if (!response.ok) throw new Error('Поиск временно недоступен')
      const data = (await response.json()).data as Hit[]
      setResults(data)
      if (!data.length) setStatus('Нет доступных результатов. Попробуйте уточнить запрос.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Ошибка поиска') }
    finally { setBusy(false) }
  }
  const form=<form className="global-search" role="search" aria-label="Поиск документов" onSubmit={event=>{event.preventDefault();void search()}}>
    <label><span className="sr-only">Поиск по имени и содержимому</span><Icon name="search"/><input placeholder="Поиск файлов и документов…" required minLength={2} maxLength={200} value={query} onChange={event=>setQuery(event.target.value)} /></label>
    <button aria-label="Найти" disabled={busy}>{busy ? '…' : '↵'}</button>
    {(query || results.length>0 || status) && <button type="button" aria-label="Очистить" onClick={()=>{setResults([]);setStatus('');setQuery('')}}>×</button>}
  </form>
  return <section className="search-results" aria-label="Результаты поиска">
    {host ? createPortal(form,host) : form}
    <p role="status">{status}</p>
    {results.length>0 && <ul>{results.map(hit=><li key={hit.id}><button onClick={()=>void onOpen(hit).catch(()=>setStatus('Документ больше недоступен'))}>{hit.name}</button>{hit.snippet && <p>{hit.snippet}</p>}</li>)}</ul>}
  </section>
}
