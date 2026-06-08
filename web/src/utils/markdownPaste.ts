import TurndownService from 'turndown'

const turndown = new TurndownService({
  headingStyle: 'atx',
  bulletListMarker: '-',
  codeBlockStyle: 'fenced',
  emDelimiter: '_',
})

turndown.addRule('taskListItem', {
  filter: node => node.nodeName === 'LI' && typeof node.querySelector === 'function' && Boolean(node.querySelector('input[type="checkbox"]')),
  replacement(content, node) {
    const checked = node.querySelector('input[type="checkbox"]')?.hasAttribute('checked') ? 'x' : ' '
    return `- [${checked}] ${content.replace(/\n+/g, ' ').trim()}\n`
  },
})

turndown.addRule('underline', {
  filter: ['u'],
  replacement: content => `<u>${content}</u>`,
})

export function htmlToMarkdown(html: string): string {
  return turndown
    .turndown(html)
    .replace(/^([-*+]) {2,}/gm, '$1 ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export function replaceBlobImageSources(markdown: string, blobNames: Map<string, string>): string {
  let result = markdown
  for (const [blobUrl, fileName] of blobNames) {
    const escaped = blobUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    result = result.replace(new RegExp(`!\\[[^\\]]*\\]\\(${escaped}\\)`, 'g'), `![${fileName}](${fileName})`)
  }
  return result
}

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
