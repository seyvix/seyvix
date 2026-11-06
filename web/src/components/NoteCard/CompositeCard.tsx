import { Link } from 'react-router'
import AuthImage from '../AuthImage/AuthImage'
import { InlineMarkdown } from '../Markdown/InlineMarkdown'
import type { Note, NoteObject } from '../../types'
import { chooseCompositeCardVisualObject, getCompositePreviewObjects } from '../../utils/noteCardPresentation'
import { getObjectDisplayMarkdown, getObjectDisplayText, getObjectPreviewSource } from '../../utils/notePreview'
import {
  densityClassName,
  DocChip,
  LinkFavicon,
  MediaPlaceholder,
  SearchMatchSnippet,
  SoftOverlay,
  type TagClickHandler,
} from './CardParts'
import { MultiObjectPreview } from './MultiObjectPreview'
import { VideoPreviewFrame } from './VideoPreviewFrame'
import {
  documentThumb,
  fallbackColor,
  firstObjectsByType,
  intrinsicRatioStyle,
  isUrlOnlyText,
  notePageHref,
  textDensity,
  visualRatioStyle,
} from './cardModel'
import styles from './NoteCard.module.css'

function CompositeCover({ note, previewObjects }: { note: Note; previewObjects: NoteObject[] }) {
  if (previewObjects.length > 1) {
    return <MultiObjectPreview visualObjs={previewObjects} fallback={fallbackColor(note.id)} />
  }
  const first = firstObjectsByType(note.objects)
  if (first.image) {
    return <AuthImage src={getObjectPreviewSource(first.image)} alt="" className={styles.compositeCoverImg} />
  }
  if (first.video) {
    return first.video.thumbnailUrl
      ? <VideoPreviewFrame src={first.video.thumbnailUrl} className={styles.compositeCoverImg} object={first.video} />
      : <MediaPlaceholder type="video" className={styles.compositeCoverEmpty} />
  }
  if (first.audio) {
    return <MediaPlaceholder type="audio" className={styles.compositeCoverEmpty} />
  }
  if (first.document) {
    const thumb = documentThumb(first.document)
    return thumb
      ? <AuthImage src={thumb} alt="" className={styles.compositeCoverImg} style={intrinsicRatioStyle(first.document)} />
      : <MediaPlaceholder type="document" className={styles.compositeCoverEmpty} label={first.document.filename ?? null} />
  }
  if (first.link) {
    if (first.link.thumbnailUrl) {
      return <AuthImage src={first.link.thumbnailUrl} alt="" className={styles.compositeCoverImg} />
    }
    const links = note.objects.filter(obj => obj.type === 'link').slice(0, 4)
    return (
      <div className={styles.compositeCoverEmpty}>
        <div className={styles.linkCoverInner}>
          <div className={styles.linkFaviconRow}>
            {links.map(link => <LinkFavicon key={link.id} url={link.content} />)}
          </div>
        </div>
      </div>
    )
  }
  return (
    <div className={styles.compositeCoverEmpty}>
      {first.text && <span className={styles.compositeCoverText}>{getObjectDisplayText(first.text, 240)}</span>}
    </div>
  )
}

/** Mixed-content note: visual cover, overlaid or footer text, document chips. */
export function CompositeCard({ note, onTagClick }: { note: Note; onTagClick?: TagClickHandler }) {
  const textObj = firstObjectsByType(note.objects).text
  const docs = note.objects.filter(obj => obj.type === 'document')
  const visualObject = chooseCompositeCardVisualObject(note.objects)
  const previewObjects = getCompositePreviewObjects(note.objects)
  const text = textObj ? getObjectDisplayMarkdown(textObj) : null
  const textIsUrl = isUrlOnlyText(textObj)
  const overlayText = Boolean(visualObject && text && !textIsUrl)

  return (
    <Link
      draggable={false}
      to={notePageHref(note)}
      className={`${styles.card} ${styles.cardMedia} ${styles.cardComposite}`}
      style={visualRatioStyle(visualObject, previewObjects.length > 1 ? 1.12 : textObj ? 0.92 : 1.18)}
    >
      <div className={styles.compositeCover}>
        <CompositeCover note={note} previewObjects={previewObjects} />
        <SoftOverlay
          note={note}
          description={overlayText && text ? { text, source: textObj?.source } : null}
          onTagClick={onTagClick}
        />
      </div>

      {note.searchMatches?.length ? (
        <div className={styles.cardFooter}>
          <SearchMatchSnippet note={note} />
        </div>
      ) : null}

      {docs.length > 0 && (
        <div className={`${styles.cardFooter} ${styles.attachmentFooter}`}>
          <div className={styles.compositeChips}>
            {docs.slice(0, 2).map(doc => <DocChip key={doc.id} obj={doc} />)}
            {docs.length > 2 && <span className={styles.moreTag}>+{docs.length - 2}</span>}
          </div>
        </div>
      )}

      {!overlayText && textObj && text && !textIsUrl && (
        <div className={`${styles.cardFooter} ${densityClassName(textDensity(text))}`}>
          <SearchMatchSnippet note={note} />
          <div className={styles.excerpt}><InlineMarkdown text={text} source={textObj.source} /></div>
        </div>
      )}
    </Link>
  )
}
