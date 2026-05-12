export type MarkdownBlock =
  | { type: 'heading'; level: 1 | 2 | 3; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'bulletList'; items: string[] }
  | { type: 'orderedList'; items: string[] }
  | { type: 'taskList'; items: Array<{ checked: boolean; text: string }> }
  | { type: 'blockquote'; text: string }
  | { type: 'code'; language: string | null; text: string }
  | { type: 'divider' }

function isBlank(line: string) {
  return line.trim().length === 0
}

function isBlockStart(line: string) {
  const trimmed = line.trim()
  return /^(#{1,3})\s+/.test(trimmed) ||
    /^([-*])\s+\[[ xX]\]\s+/.test(trimmed) ||
    /^([-*])\s+/.test(trimmed) ||
    /^\d+\.\s+/.test(trimmed) ||
    /^>\s?/.test(trimmed) ||
    /^-{3,}$/.test(trimmed) ||
    /^```/.test(trimmed)
}

export function parseMarkdownBlocks(markdown: string): MarkdownBlock[] {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n')
  const blocks: MarkdownBlock[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    const trimmed = line.trim()

    if (isBlank(line)) {
      index += 1
      continue
    }

    const codeMatch = /^```([A-Za-z0-9_-]+)?\s*$/.exec(trimmed)
    if (codeMatch) {
      const language = codeMatch[1] ?? null
      const body: string[] = []
      index += 1
      while (index < lines.length && !/^```\s*$/.test(lines[index].trim())) {
        body.push(lines[index])
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push({ type: 'code', language, text: body.join('\n') })
      continue
    }

    const headingMatch = /^(#{1,3})\s+(.+)$/.exec(trimmed)
    if (headingMatch) {
      blocks.push({
        type: 'heading',
        level: headingMatch[1].length as 1 | 2 | 3,
        text: headingMatch[2].trim(),
      })
      index += 1
      continue
    }

    if (/^-{3,}$/.test(trimmed)) {
      blocks.push({ type: 'divider' })
      index += 1
      continue
    }

    if (/^>\s?/.test(trimmed)) {
      const quote: string[] = []
      while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
        quote.push(lines[index].trim().replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push({ type: 'blockquote', text: quote.join('\n').trim() })
      continue
    }

    if (/^[-*]\s+\[[ xX]\]\s+/.test(trimmed)) {
      const items: Array<{ checked: boolean; text: string }> = []
      while (index < lines.length) {
        const match = /^[-*]\s+\[([ xX])\]\s+(.+)$/.exec(lines[index].trim())
        if (!match) break
        items.push({ checked: match[1].toLowerCase() === 'x', text: match[2].trim() })
        index += 1
      }
      blocks.push({ type: 'taskList', items })
      continue
    }

    if (/^[-*]\s+/.test(trimmed)) {
      const items: string[] = []
      while (index < lines.length) {
        const match = /^[-*]\s+(.+)$/.exec(lines[index].trim())
        if (!match) break
        items.push(match[1].trim())
        index += 1
      }
      blocks.push({ type: 'bulletList', items })
      continue
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = []
      while (index < lines.length) {
        const match = /^\d+\.\s+(.+)$/.exec(lines[index].trim())
        if (!match) break
        items.push(match[1].trim())
        index += 1
      }
      blocks.push({ type: 'orderedList', items })
      continue
    }

    const paragraph: string[] = [trimmed]
    index += 1
    while (index < lines.length && !isBlank(lines[index]) && !isBlockStart(lines[index])) {
      paragraph.push(lines[index].trim())
      index += 1
    }
    blocks.push({ type: 'paragraph', text: paragraph.join('\n') })
  }

  return blocks
}
