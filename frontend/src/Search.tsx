import { useState } from 'react'

type Hit = { id: string; name: string; resource_type: string; department_id: string; snippet: string }
export function Search({ onOpen }: { onOpen: (hit: Hit) => Promise<void> }) {
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
  return <section aria-label="Поиск документов">
    <form onSubmit={event=>{event.preventDefault();void search()}}>
      <label>Поиск по имени и содержимому <input required minLength={2} maxLength={200} value={query} onChange={event=>setQuery(event.target.value)} /></label>
      <button disabled={busy}>{busy ? 'Поиск…' : 'Найти'}</button>
      <button type="button" onClick={()=>{setResults([]);setStatus('');setQuery('')}}>Очистить</button>
    </form>
    <p role="status">{status}</p>
    <ul>{results.map(hit=><li key={hit.id}><button onClick={()=>void onOpen(hit).catch(()=>setStatus('Документ больше недоступен'))}>{hit.name}</button>{hit.snippet && <p>{hit.snippet}</p>}</li>)}</ul>
  </section>
}
