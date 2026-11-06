import { Link } from 'react-router'
import type { Note } from '../../types'
import { chooseCardRatioObject, isCardVisualObjectType } from '../../utils/noteCardPresentation'
import { getObjectDisplayMarkdown } from '../../utils/notePreview'
import { CollectionStats, SearchMatchSnippet, SoftOverlay, type TagClickHandler } from './CardParts'
import { MultiObjectPreview } from './MultiObjectPreview'
import { fallbackColor, firstObjectsByType, notePageHref, visualRatioStyle } from './cardModel'
import styles from './NoteCard.module.css'

/** Collection of child notes: mosaic cover + per-type counters. */
export function CollectionCard({ note, onTagClick }: { note: Note; onTagClick?: TagClickHandler }) {
  const visualObjs = note.objects.filter(obj => isCardVisualObjectType(obj.type)).slice(0, 5)
  const textObj = firstObjectsByType(note.objects).text
  const text = textObj ? getObjectDisplayMarkdown(textObj) : null

  return (
    <Link
      draggable={false}
      to={notePageHref(note)}
      className={`${styles.card} ${styles.cardMedia} ${styles.cardCollection}`}
      style={visualRatioStyle(chooseCardRatioObject(visualObjs), visualObjs.length > 2 ? 1.12 : 1.05)}
    >
      <div className={styles.collectionVisual}>
        <MultiObjectPreview visualObjs={visualObjs} fallback={fallbackColor(note.id)} />
      </div>
      <SoftOverlay note={note} description={textObj && text ? { text, source: textObj.source } : null} onTagClick={onTagClick}>
        <div className={styles.overlayMetaCluster}>
          <CollectionStats objects={note.objects} />
        </div>
      </SoftOverlay>
      {note.searchMatches?.length ? (
        <div className={styles.cardFooter}>
          <SearchMatchSnippet note={note} />
        </div>
      ) : null}
    </Link>
  )
}
