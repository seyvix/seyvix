import { Link } from 'react-router'
import AuthImage from '../AuthImage/AuthImage'
import { InlineMarkdown } from '../Markdown/InlineMarkdown'
import type { Note, NoteObject } from '../../types'
import { getNoteDisplayTitle } from '../../utils/noteCardPresentation'
import { getObjectDisplayMarkdown, getObjectPreviewSource } from '../../utils/notePreview'
import {
  CardMeta,
  CardTitle,
  densityClassName,
  MediaPlaceholder,
  SavedDate,
  SearchMatchSnippet,
  SoftOverlay,
  type TagClickHandler,
} from './CardParts'
import { VideoPreviewFrame } from './VideoPreviewFrame'
import { documentThumb, firstObjectsByType, notePageHref, textDensity, visualRatioStyle } from './cardModel'
import styles from './NoteCard.module.css'

function SimpleVisual({ obj }: { obj: NoteObject }) {
  if (obj.type === 'image') {
    return <AuthImage className={styles.simpleImageMedia} src={getObjectPreviewSource(obj)} alt="" />
  }
  if (obj.type === 'video') {
    return obj.thumbnailUrl
      ? <VideoPreviewFrame className={styles.simpleImageMedia} src={obj.thumbnailUrl} object={obj} />
      : <MediaPlaceholder type="video" className={styles.simpleImageMedia} />
  }
  if (obj.type === 'document') {
    const thumb = documentThumb(obj)
    return thumb
      ? <AuthImage className={styles.simpleImageMedia} src={thumb} alt="" />
      : <MediaPlaceholder type="document" className={styles.simpleImageMedia} label={obj.filename ?? null} />
  }
  return <MediaPlaceholder type="audio" className={styles.simpleImageMedia} />
}

/** Single-object note: a full-bleed media card, media with overlaid text, or a text card. */
export function SimpleCard({ note, onTagClick }: { note: Note; onTagClick?: TagClickHandler }) {
  const first = firstObjectsByType(note.objects)
  const mediaObj = first.image ?? first.video ?? first.audio ?? first.document
  const textObj = first.text
  const text = textObj ? getObjectDisplayMarkdown(textObj) : null
  const href = notePageHref(note)

  if (mediaObj && !textObj) {
    return (
      <Link
        draggable={false}
        to={href}
        className={`${styles.card} ${styles.cardMedia} ${styles.cardSimpleImage}`}
        style={visualRatioStyle(mediaObj, mediaObj.type === 'audio' ? 1.32 : 0.82)}
      >
        <SimpleVisual obj={mediaObj} />
        <SoftOverlay note={note} onTagClick={onTagClick} />
      </Link>
    )
  }

  const title = getNoteDisplayTitle(note, textObj?.content)

  if (mediaObj && textObj) {
    return (
      <Link
        draggable={false}
        to={href}
        className={`${styles.card} ${styles.cardMedia} ${styles.cardSimpleImage} ${styles.cardImageText} ${densityClassName(textDensity(text))}`}
        style={visualRatioStyle(mediaObj, mediaObj.type === 'audio' ? 1.24 : text && text.length > 220 ? 0.92 : 1.08)}
      >
        <SimpleVisual obj={mediaObj} />
        <SoftOverlay
          note={note}
          title={title}
          description={text ? { text, source: textObj.source } : null}
          onTagClick={onTagClick}
        />
      </Link>
    )
  }

  return (
    <Link
      draggable={false}
      to={href}
      className={`${styles.card} ${styles.cardSimple} ${styles.cardTextOnly} ${densityClassName(textDensity(text))}`}
    >
      <div className={styles.cardTextHead}>
        <SavedDate createdAt={note.createdAt} />
        <CardTitle title={title} />
      </div>
      <SearchMatchSnippet note={note} />
      {textObj && text && (
        <div className={title ? styles.excerpt : `${styles.excerpt} ${styles.excerptAsTitle}`}>
          <InlineMarkdown text={text} source={textObj.source} />
        </div>
      )}
      <CardMeta note={note} onTagClick={onTagClick} />
    </Link>
  )
}
