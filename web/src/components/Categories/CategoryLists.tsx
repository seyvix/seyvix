import { Link } from 'react-router'
import { ArrowRight, ChevronRight, FileText, Link2, Tags } from 'lucide-react'
import AuthImage from '../AuthImage/AuthImage'
import type { Folder, FolderNoteSummary } from '../../types'
import { getObjectPreviewSource } from '../../utils/notePreview'
import {
  categoryUrl,
  cleanPreviewText,
  formatCategoryNoteDate,
  noteTextPreview,
  noteVisualObject,
} from './categoryModel'
import styles from './Categories.module.css'

export function Breadcrumbs({ category }: { category: Folder }) {
  const segments = category.path.split('/')
  return (
    <div className={styles.breadcrumbs} aria-label="Путь категории">
      {segments.map((segment, index) => {
        const path = segments.slice(0, index + 1).join('/')
        return (
          <span key={path} className={styles.crumb}>
            {index > 0 && <ChevronRight size={13} strokeWidth={1.8} />}
            <Link to={categoryUrl(path)}>{segment}</Link>
          </span>
        )
      })}
    </div>
  )
}

export function CategoryGrid({ categories }: { categories: Folder[] }) {
  return (
    <div className={styles.categoryGrid}>
      {categories.map(category => (
        <Link key={category.id} to={categoryUrl(category.path)} className={styles.categoryCard}>
          <span className={styles.categoryCardIcon}><Tags size={16} strokeWidth={1.8} /></span>
          <span className={styles.categoryCardBody}>
            <strong>{category.name}</strong>
            <small>{category.path}</small>
          </span>
          <ArrowRight size={15} strokeWidth={1.8} />
        </Link>
      ))}
    </div>
  )
}

function NotePreview({ note, textPreview }: { note: FolderNoteSummary; textPreview: string | null }) {
  const visual = noteVisualObject(note)
  if (visual) {
    return (
      <span className={styles.notePreview} aria-hidden>
        <AuthImage src={getObjectPreviewSource(visual)} alt="" className={styles.notePreviewImage} />
      </span>
    )
  }
  if (textPreview) {
    return <span className={`${styles.notePreview} ${styles.notePreviewText}`} aria-hidden>{textPreview}</span>
  }
  return (
    <span className={styles.noteIcon} aria-hidden>
      {note.objects.some(obj => obj.type === 'link') ? <Link2 size={15} strokeWidth={1.8} /> : <FileText size={15} strokeWidth={1.8} />}
    </span>
  )
}

function NoteRow({ note, selectedPath }: { note: FolderNoteSummary; selectedPath: string }) {
  const notePath = note.taxonomyCategory?.path
  const title = cleanPreviewText(note.title)
  const preview = noteTextPreview(note)

  return (
    <Link to={`/notes/${note.slug}`} className={styles.noteRow}>
      <NotePreview note={note} textPreview={preview} />
      <span className={styles.noteBody}>
        <strong className={title || preview ? undefined : styles.noteTitleMuted}>{title || preview || 'Без заголовка'}</strong>
        <span className={styles.noteMeta}>
          <small>{formatCategoryNoteDate(note)}</small>
          {title && preview && title !== preview && <small>{preview}</small>}
        </span>
      </span>
      {notePath && notePath !== selectedPath && <span className={styles.noteCategory}>{notePath}</span>}
      <ArrowRight size={14} strokeWidth={1.8} />
    </Link>
  )
}

export function CategoryNotesList({ notes, selectedPath }: { notes: FolderNoteSummary[]; selectedPath: string }) {
  return (
    <div className={styles.notesList}>
      {notes.map(note => <NoteRow key={note.id} note={note} selectedPath={selectedPath} />)}
    </div>
  )
}
