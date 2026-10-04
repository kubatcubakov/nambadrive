import { useState } from 'react'

export function Upload() {
  const [parent, setParent] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  async function upload() {
    if (!file || !parent) return
    setBusy(true)
    setStatus('Загрузка…')
    try {
      const csrf = await fetch('/api/v1/auth/csrf')
      if (!csrf.ok) throw new Error('Войдите повторно')
      const token = ((await csrf.json()) as { data: { csrf_token: string } }).data.csrf_token
      const query = new URLSearchParams({ parent_id: parent, filename: file.name })
      const response = await fetch('/api/v1/documents/upload?' + query, {
        method: 'POST', headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/octet-stream' }, body: file,
      })
      if (!response.ok) throw new Error(response.status === 413 ? 'Файл превышает лимит' : 'Загрузка отклонена: проверьте права и формат файла')
      setStatus('Файл принят на антивирусную проверку. Он появится в папке после успешной проверки.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Ошибка загрузки') }
    finally { setBusy(false) }
  }
  return <section>
    <h2>Загрузить файл</h2>
    <label>Папка (UUID) <input value={parent} onChange={e => setParent(e.target.value)} /></label>
    <input aria-label="Выберите файл" type="file" accept=".docx,.xlsx,.pptx,.pdf,.zip,.jpg,.jpeg,.png,.dwg,.psd,.txt,.csv,.json,.xml" onChange={e => setFile(e.target.files?.[0] ?? null)} />
    <button disabled={busy || !file || !parent} onClick={() => void upload()}>Загрузить</button>
    <p role="status">{status}</p>
  </section>
}
