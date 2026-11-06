import { memo, useMemo } from 'react'
import type { SourceMetadata } from '../../types'
import { parseMarkdownBlocks, type MarkdownBlock } from '../../utils/markdownBlocks'
import { renderInlineMarkdown, type InlineMarkdownOptions } from './renderInlineMarkdown'
import styles from './Markdown.module.css'

type TaskToggle = (taskIndex: number, checked: boolean) => void

function MarkdownBlockView({
  block,
  options,
  keyPrefix,
  taskStartIndex,
  onTaskToggle,
}: {
  block: MarkdownBlock
  options: InlineMarkdownOptions
  keyPrefix: string
  taskStartIndex: number
  onTaskToggle?: TaskToggle
}) {
  switch (block.type) {
    case 'heading': {
      const Heading = `h${block.level}` as 'h1' | 'h2' | 'h3'
      return <Heading>{renderInlineMarkdown(block.text, options, keyPrefix)}</Heading>
    }
    case 'paragraph':
      return <p>{renderInlineMarkdown(block.text, options, keyPrefix)}</p>
    case 'blockquote':
      return <blockquote>{renderInlineMarkdown(block.text, options, keyPrefix)}</blockquote>
    case 'bulletList':
    case 'orderedList': {
      const List = block.type === 'bulletList' ? 'ul' : 'ol'
      return (
        <List>
          {block.items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInlineMarkdown(item, options, `${keyPrefix}-li-${itemIndex}`)}</li>
          ))}
        </List>
      )
    }
    case 'taskList':
      return (
        <ul className={styles.markdownTaskList}>
          {block.items.map((item, itemIndex) => (
            <li key={itemIndex}>
              <input
                type="checkbox"
                checked={item.checked}
                readOnly={!onTaskToggle}
                disabled={!onTaskToggle}
                onClick={event => event.stopPropagation()}
                onChange={event => onTaskToggle?.(taskStartIndex + itemIndex, event.currentTarget.checked)}
              />
              <span>{renderInlineMarkdown(item.text, options, `${keyPrefix}-task-${itemIndex}`)}</span>
            </li>
          ))}
        </ul>
      )
    case 'code':
      return <pre><code>{block.text}</code></pre>
    case 'divider':
      return <hr />
  }
}

/** Block-level markdown renderer for note bodies and captions (interactive links, task toggles). */
export const MarkdownText = memo(function MarkdownText({
  text,
  source,
  className,
  onTaskToggle,
}: {
  text: string
  source?: SourceMetadata | null
  className?: string
  onTaskToggle?: TaskToggle
}) {
  const blocks = useMemo(() => parseMarkdownBlocks(text), [text])
  const options = useMemo<InlineMarkdownOptions>(() => ({ source, interactive: true }), [source])

  let taskStartIndex = 0
  return (
    <div className={className ? `${styles.markdownText} ${className}` : styles.markdownText}>
      {blocks.map((block, index) => {
        const start = taskStartIndex
        if (block.type === 'taskList') taskStartIndex += block.items.length
        return (
          <MarkdownBlockView
            key={index}
            block={block}
            options={options}
            keyPrefix={`md-${index}`}
            taskStartIndex={start}
            onTaskToggle={onTaskToggle}
          />
        )
      })}
    </div>
  )
})
