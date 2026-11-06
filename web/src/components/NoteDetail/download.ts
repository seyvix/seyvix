import { apiFetch } from '../../lib/apiClient'

/** Downloads a protected API file with the bearer token (an <a download> can't send it). */
export async function downloadAuthenticated(url: string, filename?: string): Promise<void> {
  const response = await apiFetch(url)
  if (!response.ok) throw new Error(`Download failed with ${response.status}`)
  const objectUrl = URL.createObjectURL(await response.blob())
  try {
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = filename ?? url.split('/').pop() ?? 'download'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  } finally {
    // Revoke after the click has been dispatched; the browser keeps the download alive.
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
  }
}

export function startDownload(url: string, filename?: string) {
  downloadAuthenticated(url, filename).catch(error => {
    console.error('Download failed', error)
    window.alert('Не удалось скачать файл.')
  })
}
