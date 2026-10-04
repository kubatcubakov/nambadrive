import { useState } from 'react'

export function Upload({ parentId }: { parentId?: string }) {
  const [parent, setParent] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  async function upload() {
    const target = parentId || parent
    if (!files.length || !target) return
    setBusy(true)
    setStatus('Загрузка…')
    try {
      const csrf = await fetch('/api/v1/auth/csrf')
      if (!csrf.ok) throw new Error('Войдите повторно')
      const token = ((await csrf.json()) as { data: { csrf_token: string } }).data.csrf_token
      let completed = 0
      for (const file of files) {
      const query = new URLSearchParams({ parent_id: target, filename: file.name })
      const response = await fetch('/api/v1/documents/upload?' + query, {
        method: 'POST', headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/octet-stream' }, body: file,
      })
      if (!response.ok) throw new Error(response.status === 413 ? 'Файл превышает лимит' : 'Загрузка отклонена: проверьте права и формат файла')
      completed += 1
      setStatus(`Принято на проверку: ${completed} из ${files.length}`)
      }
      setStatus(`Принято файлов: ${completed}. Они появятся в папке после антивирусной проверки.`)
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Ошибка загрузки') }
    finally { setBusy(false) }
  }
  return <section>
    <h2>Загрузить файл</h2>
    {!parentId && <label>Папка (UUID) <input value={parent} onChange={e => setParent(e.target.value)} /></label>}
    <input aria-label="Выберите файл" type="file" multiple accept=".docx,.xlsx,.pptx,.pdf,.zip,.jpg,.jpeg,.png,.dwg,.psd,.txt,.csv,.json,.xml" onChange={e => setFiles(Array.from(e.target.files ?? []))} />
    <button disabled={busy || !files.length || !(parentId || parent)} onClick={() => void upload()}>Загрузить</button>
    <p role="status">{status}</p>
  </section>
}
