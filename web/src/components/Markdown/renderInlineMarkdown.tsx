import type { MouseEvent, ReactNode } from 'react'
import type { SourceMetadata } from '../../types'
import { openAuthenticatedAsset } from '../../utils/authenticatedBlobUrl'
import styles from './Markdown.module.css'

type EmojiAsset = { data_url?: string; fallback?: string }

export interface InlineMarkdownOptions {
  /** Source metadata of the object (custom Telegram emoji assets live there). */
  source?: SourceMetadata | null
  /**
   * Interactive mode renders real anchors. Cards are already wrapped in a link, so they render
   * labels only (nested anchors are invalid HTML and would hijack the card click).
   */
  interactive: boolean
}

// favicon-link | custom emoji | image | link | **bold** | __bold__ | `code` | <u>underline</u> | _italic_
const INLINE_PATTERN =
  /!\[favicon\]\(([^)]+)\)\s+\[([^\]]+)\]\(([^)]+)\)|\{\{tg_emoji:([0-9]+)\|([^}]+)\}\}|!\[([^\]]*)\]\(([^)]+)\)|\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|<u>(.*?)<\/u>|_([^_\n]+)_/g

const SAFE_URL_RE = /^(?:https?:|mailto:|tel:|\/(?!\/)|#)/i

/** Only http(s)/mailto/tel/relative targets; anything else (javascript:, data:, …) is dropped. */
export function safeHref(value: string): string | null {
  const trimmed = value.trim()
  return SAFE_URL_RE.test(trimmed) ? trimmed : null
}

function emojiAssets(source: SourceMetadata | null | undefined): Record<string, EmojiAsset> {
  const assets = source?.metadata?.custom_emoji_assets
  return assets && typeof assets === 'object' && !Array.isArray(assets)
    ? assets as Record<string, EmojiAsset>
    : {}
}

function isProtectedAssetUrl(url: string): boolean {
  try {
    const parsed = new URL(url, window.location.origin)
    return parsed.origin === window.location.origin
      && parsed.pathname.startsWith('/api/v1/notes/')
      && parsed.pathname.includes('/asset/')
  } catch {
    return false
  }
}

function openProtectedAsset(event: MouseEvent<HTMLAnchorElement>, href: string) {
  if (!isProtectedAssetUrl(href)) return
  event.preventDefault()
  openAuthenticatedAsset(href).catch(error => {
    console.warn('Failed to open attachment', error)
  })
}

function render(
  text: string,
  options: InlineMarkdownOptions,
  assets: Record<string, EmojiAsset>,
  keyPrefix: string,
): ReactNode[] {
  const parts: ReactNode[] = []
  let lastIndex = 0

  for (const match of text.matchAll(INLINE_PATTERN)) {
    const index = match.index ?? 0
    if (index > lastIndex) parts.push(text.slice(lastIndex, index))
    const key = `${keyPrefix}-${index}`
    const [
      ,
      faviconUrl,
      faviconLabel,
      faviconHref,
      customEmojiId,
      emojiFallback,
      imageAlt,
      imageHref,
      linkLabel,
      linkHref,
      boldText,
      boldAltText,
      codeText,
      underlineText,
      italicText,
    ] = match

    if (customEmojiId) {
      const asset = assets[customEmojiId]
      parts.push(asset?.data_url
        ? <img key={key} className={styles.inlineTelegramEmoji} src={asset.data_url} alt={asset.fallback || emojiFallback} title={customEmojiId} />
        : <span key={key} title={customEmojiId}>{emojiFallback}</span>)
    } else if (faviconHref) {
      const href = options.interactive ? safeHref(faviconHref) : null
      const favicon = safeHref(faviconUrl)
      parts.push(href ? (
        <a key={key} className={styles.inlineMarkdownLink} href={href} target="_blank" rel="noopener noreferrer">
          {favicon && <img src={favicon} alt="" />}
          <span>{faviconLabel}</span>
        </a>
      ) : <span key={key}>{faviconLabel}</span>)
    } else if (imageHref) {
      const href = options.interactive ? safeHref(imageHref) : null
      const label = imageAlt || imageHref
      parts.push(href ? (
        <a
          key={key}
          className={styles.inlineMarkdownAttachment}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={event => openProtectedAsset(event, href)}
        >
          {label}
        </a>
      ) : <span key={key}>{label}</span>)
    } else if (linkHref) {
      const href = options.interactive ? safeHref(linkHref) : null
      parts.push(href
        ? <a key={key} href={href} target="_blank" rel="noopener noreferrer">{linkLabel}</a>
        : <span key={key}>{linkLabel}</span>)
    } else if (boldText || boldAltText) {
      parts.push(<strong key={key}>{render(boldText ?? boldAltText, options, assets, key)}</strong>)
    } else if (codeText) {
      parts.push(<code key={key}>{codeText}</code>)
    } else if (underlineText) {
      parts.push(<u key={key}>{render(underlineText, options, assets, key)}</u>)
    } else if (italicText) {
      parts.push(<em key={key}>{render(italicText, options, assets, key)}</em>)
    }
    lastIndex = index + match[0].length
  }

  if (lastIndex < text.length) parts.push(text.slice(lastIndex))
  return parts
}

/** Renders the inline markdown dialect produced by the backend/Telegram ingest as React nodes. */
export function renderInlineMarkdown(text: string, options: InlineMarkdownOptions, keyPrefix = 'md'): ReactNode[] {
  return render(text, options, emojiAssets(options.source), keyPrefix)
}
