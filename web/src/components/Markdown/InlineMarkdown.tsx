import { memo, useMemo } from 'react'
import type { SourceMetadata } from '../../types'
import { renderInlineMarkdown } from './renderInlineMarkdown'

/** Non-interactive inline markdown (cards and previews that sit inside a link). */
export const InlineMarkdown = memo(function InlineMarkdown({
  text,
  source,
}: {
  text: string
  source?: SourceMetadata | null
}) {
  const nodes = useMemo(
    () => renderInlineMarkdown(text, { source, interactive: false }, 'inline'),
    [text, source],
  )
  return <>{nodes}</>
})
