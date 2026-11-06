import { memo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { ExternalLink, X } from 'lucide-react'
import AuthImage from '../AuthImage/AuthImage'
import { MarkdownText } from '../Markdown/MarkdownText'
import type { NoteObject } from '../../types'
import type { NoteDetailObjectModel } from '../../utils/noteCardPresentation'
import { AssetViewer } from './AssetViewer'
import { ObjectKindIcon, ObjectSourceInline } from './DetailParts'
import { formatBytes, formatDetailDate, objectDomId, objectKindLabel } from './format'
import { FullscreenDialog } from './FullscreenDialog'
import { MediaPlayer } from './MediaPlayer'
import mediaStyles from './MediaPlayer.module.css'
import styles from './NoteDetail.module.css'

export interface DetailStreamHandlers {
  onOpenViewer: (id: string) => void
  onTextChange: (id: string, value: string) => void
  onToggleTextTask: (obj: NoteObject, taskIndex: number, checked: boolean) => void
  onRemove: (id: string, slug?: string) => void
}

function DeleteButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className={styles.objDeleteBtn} onClick={onClick} aria-label="Убрать из заметки">
      <X size={12} />
    </button>
  )
}

function ImageObject({ obj, children }: { obj: NoteObject; children: ReactNode }) {
  const [fullscreenOpen, setFullscreenOpen] = useState(false)
  const title = obj.caption?.trim() || obj.filename || 'Изображение'
  return (
    <div className={`${styles.objWrapper} ${styles.objImage}`}>
      <button type="button" className={styles.imagePreviewButton} onClick={() => setFullscreenOpen(true)} title="Открыть на весь экран">
        <AuthImage src={obj.content} alt={title} />
      </button>
      {obj.caption && <MarkdownText className={styles.objImageCaption} text={obj.caption} source={obj.source} />}
      {children}
      {fullscreenOpen && (
        <FullscreenDialog title={title} onClose={() => setFullscreenOpen(false)}>
          <AuthImage src={obj.content} alt={title} className={styles.fullscreenImage} />
        </FullscreenDialog>
      )}
    </div>
  )
}

function MediaObject({ obj, children }: { obj: NoteObject; children: ReactNode }) {
  const [fullscreenOpen, setFullscreenOpen] = useState(false)
  const title = obj.filename ?? (obj.type === 'audio' ? 'Аудио' : 'Видео')
  const sizeLabel = obj.sizeBytes !== undefined ? formatBytes(obj.sizeBytes) : undefined
  return (
    <div className={styles.objWrapper}>
      <div className={styles.mediaBox}>
        <MediaPlayer obj={obj} title={title} sizeLabel={sizeLabel} onOpenFullscreen={() => setFullscreenOpen(true)} />
      </div>
      {fullscreenOpen && (
        <FullscreenDialog title={title} onClose={() => setFullscreenOpen(false)}>
          <div className={obj.type === 'audio' ? mediaStyles.fullscreenAudioStage : mediaStyles.fullscreenMediaStage}>
            <MediaPlayer obj={obj} title={title} sizeLabel={sizeLabel} autoPlay isFullscreen />
          </div>
        </FullscreenDialog>
      )}
      {children}
    </div>
  )
}

function ObjectChrome({ item }: { item: NoteDetailObjectModel }) {
  const obj = item.object
  return (
    <div className={styles.objectChrome}>
      <div className={styles.objectChromeMain}>
        <span className={styles.objectKindBadge}>
          <ObjectKindIcon type={obj.type} />
          {objectKindLabel(obj.type)}
        </span>
        <span className={styles.objectChromeIndex}>#{item.index + 1}</span>
        <span>{formatDetailDate(obj.createdAt) ?? 'нет даты'}</span>
      </div>
      <ObjectSourceInline source={obj.source} />
      {item.childHref && (
        <Link className={styles.objectOpenLink} to={item.childHref} title="Открыть дочернюю заметку">
          <ExternalLink size={13} />
          <span>Открыть</span>
        </Link>
      )}
    </div>
  )
}

const DetailObjectSection = memo(function DetailObjectSection({
  item,
  isEditing,
  canEditText,
  editValue,
  isViewerOpen,
  handlers,
}: {
  item: NoteDetailObjectModel
  isEditing: boolean
  canEditText: boolean
  editValue: string | undefined
  isViewerOpen: boolean
  handlers: DetailStreamHandlers
}) {
  const obj = item.object
  const remove = () => handlers.onRemove(obj.id, obj.slug)
  const companion = (
    <AssetViewer
      obj={obj}
      noteId={item.viewerNoteId}
      isEditing={false}
      isOpen={isViewerOpen}
      onOpen={() => handlers.onOpenViewer(obj.id)}
      onDelete={remove}
    />
  )

  let body: ReactNode
  if (obj.type === 'text') {
    body = isEditing && canEditText ? (
      <div className={styles.objWrapper}>
        <textarea
          className={styles.objTextarea}
          value={editValue ?? obj.content}
          onChange={event => handlers.onTextChange(obj.id, event.target.value)}
        />
        <DeleteButton onClick={remove} />
      </div>
    ) : (
      <div className={styles.objWrapper}>
        <MarkdownText
          className={styles.objText}
          text={obj.content}
          source={obj.source}
          onTaskToggle={isEditing ? undefined : (taskIndex, checked) => handlers.onToggleTextTask(obj, taskIndex, checked)}
        />
        {isEditing && <DeleteButton onClick={remove} />}
      </div>
    )
  } else if (obj.type === 'image') {
    body = (
      <ImageObject obj={obj}>
        <div className={styles.extractionCompanion}>{companion}</div>
        {isEditing && <DeleteButton onClick={remove} />}
      </ImageObject>
    )
  } else if (obj.type === 'audio' || obj.type === 'video') {
    body = (
      <MediaObject obj={obj}>
        <div className={styles.extractionCompanion}>{companion}</div>
        {isEditing && <DeleteButton onClick={remove} />}
      </MediaObject>
    )
  } else {
    body = (
      <AssetViewer
        obj={obj}
        noteId={item.viewerNoteId}
        isEditing={isEditing}
        isOpen={isViewerOpen}
        onOpen={() => handlers.onOpenViewer(obj.id)}
        onDelete={remove}
      />
    )
  }

  return (
    <section id={objectDomId(obj.id)} className={`${styles.objectSection} ${styles.detailObjectSection}`}>
      <ObjectChrome item={item} />
      <div className={styles.detailObjectBody}>{body}</div>
    </section>
  )
})

/** All objects of a note in order, each with its chrome and type-specific body. */
export function DetailStream({
  items,
  isEditing,
  canEditText,
  editTexts,
  openViewerId,
  handlers,
}: {
  items: NoteDetailObjectModel[]
  isEditing: boolean
  canEditText: boolean
  editTexts: Record<string, string>
  openViewerId: string | null
  handlers: DetailStreamHandlers
}) {
  return (
    <div className={styles.stream}>
      {items.map(item => (
        <DetailObjectSection
          key={item.object.id}
          item={item}
          isEditing={isEditing}
          canEditText={canEditText}
          editValue={editTexts[item.object.id]}
          isViewerOpen={openViewerId === item.object.id}
          handlers={handlers}
        />
      ))}
    </div>
  )
}
