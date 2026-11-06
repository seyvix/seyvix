/** Plain-text title (≤60 chars) from the first meaningful markdown line. Kept free of heavy deps. */
export function makeMarkdownTitle(markdown: string): string {
  const line = markdown
    .split('\n')
    .map(item => item.trim())
    .find(Boolean) ?? 'Новая заметка'

  return line
    .replace(/\{\{tg_emoji:[0-9]+\|([^}]+)\}\}/g, '$1')
    .replace(/^#{1,6}\s+/, '')
    .replace(/^[-*+]\s+\[[ xX]\]\s+/, '')
    .replace(/^[-*+]\s+/, '')
    .replace(/^>\s+/, '')
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[*_~`>#]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 60) || 'Новая заметка'
}
