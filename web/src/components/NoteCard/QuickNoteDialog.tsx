import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { EditorContent, useEditor, useEditorState, type Editor } from '@tiptap/react'
import { BubbleMenu } from '@tiptap/react/menus'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import Image from '@tiptap/extension-image'
import LinkExtension from '@tiptap/extension-link'
import Typography from '@tiptap/extension-typography'
import UnderlineExtension from '@tiptap/extension-underline'
import {
  Bold,
  Code2,
  Heading1,
  ImageIcon,
  Italic,
  Link2,
  List,
  ListChecks,
  ListOrdered,
  Minus,
  Paperclip,
  TextQuote,
  Underline,
} from 'lucide-react'
import { dropTargetForExternal } from '@atlaskit/pragmatic-drag-and-drop/external/adapter'
import { containsFiles, getFiles } from '@atlaskit/pragmatic-drag-and-drop/external/file'
import { useCreateNote } from '../../hooks/useCreateNote'
import { useUploadFiles } from '../../hooks/useUploadFiles'
import { useUploadContext } from '../../contexts/UploadContext'
import { htmlToMarkdown, replaceBlobImageSources } from '../../utils/markdownPaste'
import { makeMarkdownTitle } from '../../utils/markdownTitle'
import { moveSlashMenuSelection } from '../../utils/slashMenuNavigation'
import { partitionUploadFiles } from '../../utils/uploadGuard'
import styles from './QuickNoteDialog.module.css'

type SlashCommand = 'heading' | 'task' | 'image' | 'divider' | 'quote' | 'code' | 'bullet' | 'ordered'

interface SlashItem {
  id: SlashCommand
  label: string
  description: string
  icon: ReactNode
  keywords: string
}

const SLASH_ITEMS: SlashItem[] = [
  { id: 'heading', label: 'Заголовок', description: 'Крупный H1-блок', icon: <Heading1 size={18} />, keywords: 'heading заголовок h1' },
  { id: 'task', label: 'Список задач', description: 'Чеклист с галочками', icon: <ListChecks size={18} />, keywords: 'task todo задача чеклист' },
  { id: 'image', label: 'Изображение', description: 'Прикрепить картинку', icon: <ImageIcon size={18} />, keywords: 'image img фото картинка' },
  { id: 'divider', label: 'Разделитель', description: 'Горизонтальная линия', icon: <Minus size={18} />, keywords: 'divider hr линия' },
  { id: 'quote', label: 'Цитата', description: 'Выделенный блок текста', icon: <TextQuote size={18} />, keywords: 'quote цитата' },
  { id: 'code', label: 'Код', description: 'Блок моноширинного текста', icon: <Code2 size={18} />, keywords: 'code код' },
  { id: 'bullet', label: 'Маркированный список', description: 'Список с точками', icon: <List size={18} />, keywords: 'bullet list список' },
  { id: 'ordered', label: 'Нумерованный список', description: 'Список 1, 2, 3', icon: <ListOrdered size={18} />, keywords: 'ordered number список' },
]

interface SlashMenuState {
  visible: boolean
  top: number
  left: number
  query: string
}

const HIDDEN_SLASH_MENU: SlashMenuState = { visible: false, top: 0, left: 0, query: '' }

function pastedImageFiles(event: ClipboardEvent): File[] {
  return Array.from(event.clipboardData?.items ?? [])
    .filter(item => item.kind === 'file' && item.type.startsWith('image/'))
    .flatMap((item, index) => {
      const file = item.getAsFile()
      if (!file) return []
      const ext = file.type.split('/')[1] || 'png'
      return [new File([file], file.name || `pasted-image-${Date.now()}-${index + 1}.${ext}`, { type: file.type })]
    })
}

function runSlashCommand(editor: Editor, command: SlashCommand, pickImage: () => void) {
  const { selection } = editor.state
  const lineStart = selection.from - selection.$from.parentOffset
  editor.chain().focus().deleteRange({ from: lineStart, to: selection.from }).run()
  const chain = editor.chain().focus()
  switch (command) {
    case 'heading': chain.toggleHeading({ level: 1 }).run(); break
    case 'task': chain.toggleTaskList().run(); break
    case 'image': pickImage(); break
    case 'divider': chain.setHorizontalRule().run(); break
    case 'quote': chain.toggleBlockquote().run(); break
    case 'code': chain.toggleCodeBlock().run(); break
    case 'bullet': chain.toggleBulletList().run(); break
    case 'ordered': chain.toggleOrderedList().run(); break
  }
}

function promptLink(editor: Editor) {
  const previousUrl = editor.getAttributes('link').href as string | undefined
  const url = window.prompt('Ссылка', previousUrl ?? 'https://')
  if (url === null) return
  const chain = editor.chain().focus().extendMarkRange('link')
  if (url.trim()) chain.setLink({ href: url.trim() }).run()
  else chain.unsetLink().run()
}

const BUBBLE_MARKS = ['bold', 'italic', 'underline', 'link', 'code'] as const
type BubbleMark = typeof BUBBLE_MARKS[number]

function BubbleTools({ editor, onLink }: { editor: Editor; onLink: () => void }) {
  // Re-render only when the active marks change, not on every transaction.
  const active = useEditorState({
    editor,
    selector: ({ editor: instance }) => Object.fromEntries(
      BUBBLE_MARKS.map(mark => [mark, instance.isActive(mark)]),
    ) as Record<BubbleMark, boolean>,
  })
  const tools: Array<{ mark: BubbleMark; title: string; icon: ReactNode; run: () => void }> = [
    { mark: 'bold', title: 'Жирный', icon: <Bold size={18} />, run: () => editor.chain().focus().toggleBold().run() },
    { mark: 'italic', title: 'Курсив', icon: <Italic size={18} />, run: () => editor.chain().focus().toggleItalic().run() },
    { mark: 'underline', title: 'Подчеркнуть', icon: <Underline size={18} />, run: () => editor.chain().focus().toggleUnderline().run() },
    { mark: 'link', title: 'Ссылка', icon: <Link2 size={18} />, run: onLink },
    { mark: 'code', title: 'Код', icon: <Code2 size={18} />, run: () => editor.chain().focus().toggleCode().run() },
  ]
  return (
    <BubbleMenu editor={editor} className={styles.quickNoteBubble}>
      {tools.map(tool => (
        <button
          key={tool.mark}
          type="button"
          className={active[tool.mark] ? styles.quickNoteToolActive : ''}
          onMouseDown={event => {
            event.preventDefault()
            tool.run()
          }}
          title={tool.title}
        >
          {tool.icon}
        </button>
      ))}
    </BubbleMenu>
  )
}

/** Modal rich-text editor for a new note (lazy chunk: TipTap is only loaded when this opens). */
export default function QuickNoteDialog({ onClose }: { onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const slashMenuRef = useRef<HTMLDivElement>(null)
  const blobNamesRef = useRef(new Map<string, string>())
  const [files, setFiles] = useState<File[]>([])
  const [isEditorEmpty, setIsEditorEmpty] = useState(true)
  const [slashMenu, setSlashMenu] = useState<SlashMenuState>(HIDDEN_SLASH_MENU)
  const [slashSelectedIndex, setSlashSelectedIndex] = useState(0)

  const { mutate: upload } = useUploadFiles()
  const { mutate: create } = useCreateNote()
  const { pushNotice } = useUploadContext()

  const slashItems = useMemo(
    () => SLASH_ITEMS.filter(item => !slashMenu.query
      || item.keywords.includes(slashMenu.query)
      || item.label.toLowerCase().includes(slashMenu.query)),
    [slashMenu.query],
  )

  const attachFiles = useCallback((incoming: File[], editor: Editor | null) => {
    if (incoming.length === 0) return
    const { accepted, rejected } = partitionUploadFiles(incoming)
    for (const rejection of rejected) pushNotice(rejection.reason)
    if (accepted.length === 0) return
    setFiles(prev => [...prev, ...accepted])
    if (!editor) return
    accepted
      .filter(file => file.type.startsWith('image/'))
      .forEach((file, index) => {
        const name = file.name || `pasted-image-${Date.now()}-${index + 1}.png`
        const url = URL.createObjectURL(file)
        blobNamesRef.current.set(url, name)
        editor.chain().focus().setImage({ src: url, alt: name, title: name }).run()
      })
  }, [pushNotice])

  const updateSlashMenu = useCallback((editor: Editor) => {
    const { selection } = editor.state
    const root = dialogRef.current
    const match = selection.empty
      ? /^\/([\p{L}\p{N}_-]*)?$/u.exec(selection.$from.parent.textBetween(0, selection.$from.parentOffset, '\n', '\n'))
      : null
    if (!match || !root) {
      setSlashMenu(prev => (prev.visible ? HIDDEN_SLASH_MENU : prev))
      return
    }
    const coords = editor.view.coordsAtPos(selection.from)
    const bounds = root.getBoundingClientRect()
    setSlashMenu({
      visible: true,
      top: coords.bottom - bounds.top + 8,
      left: Math.max(16, coords.left - bounds.left),
      query: match[1]?.toLowerCase() ?? '',
    })
  }, [])

  // The editor is created once; its handlers read the latest UI state/actions through this ref.
  const latestRef = useRef<{
    editor: Editor | null
    slashMenu: SlashMenuState
    slashItems: SlashItem[]
    slashSelectedIndex: number
    submit: () => void
  }>({ editor: null, slashMenu, slashItems, slashSelectedIndex, submit: () => {} })
  const pickImage = useCallback(() => fileInputRef.current?.click(), [])

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] }, link: false }),
      UnderlineExtension,
      Typography,
      LinkExtension.configure({
        autolink: true,
        openOnClick: false,
        linkOnPaste: true,
        HTMLAttributes: { rel: 'noopener noreferrer nofollow' },
      }),
      Image.configure({ allowBase64: true, inline: false }),
      TaskList,
      TaskItem.configure({ nested: true }),
      Placeholder.configure({ placeholder: 'Введите / для команд или вставьте текст из Word' }),
    ],
    autofocus: 'end',
    content: '',
    immediatelyRender: false,
    editorProps: {
      attributes: { class: styles.quickNoteEditorContent },
      handlePaste: (_view, event) => {
        const images = pastedImageFiles(event)
        if (images.length === 0) return false
        event.preventDefault()
        attachFiles(images, latestRef.current.editor)
        return true
      },
      handleKeyDown: (_view, event) => {
        const { slashMenu: menu, slashItems: items, slashSelectedIndex: selected, editor: instance } = latestRef.current
        const menuOpen = menu.visible && items.length > 0
        if (event.key === 'Escape') {
          if (menu.visible) setSlashMenu(HIDDEN_SLASH_MENU)
          else onClose()
          return true
        }
        if (menuOpen && (event.key === 'ArrowDown' || event.key === 'Tab')) {
          event.preventDefault()
          setSlashSelectedIndex(index => moveSlashMenuSelection(index, items.length, 1))
          return true
        }
        if (menuOpen && event.key === 'ArrowUp') {
          event.preventDefault()
          setSlashSelectedIndex(index => moveSlashMenuSelection(index, items.length, -1))
          return true
        }
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
          latestRef.current.submit()
          return true
        }
        if (event.key === 'Enter' && menuOpen) {
          event.preventDefault()
          if (instance) runSlashCommand(instance, items[Math.min(selected, items.length - 1)].id, pickImage)
          setSlashMenu(HIDDEN_SLASH_MENU)
          return true
        }
        return false
      },
    },
    onUpdate: ({ editor: instance }) => {
      setIsEditorEmpty(instance.isEmpty)
      updateSlashMenu(instance)
    },
    onSelectionUpdate: ({ editor: instance }) => updateSlashMenu(instance),
  }, [])

  function submit() {
    const html = editor?.getHTML() ?? ''
    const markdown = replaceBlobImageSources(htmlToMarkdown(html), blobNamesRef.current).trim()
    if (files.length > 0) {
      upload({ files, text: markdown || undefined })
    } else if (markdown) {
      create({
        title: makeMarkdownTitle(markdown),
        type: 'simple',
        objects: [{ id: `txt-${Date.now()}`, type: 'text', content: markdown, createdAt: new Date().toISOString() }],
      })
    }
    onClose()
  }

  useLayoutEffect(() => {
    latestRef.current = { editor, slashMenu, slashItems, slashSelectedIndex, submit }
  })

  // Inline image previews are blob URLs; release them when the dialog goes away.
  useEffect(() => {
    const blobNames = blobNamesRef.current
    return () => {
      blobNames.forEach((_name, url) => URL.revokeObjectURL(url))
      blobNames.clear()
    }
  }, [])

  useEffect(() => {
    setSlashSelectedIndex(0)
  }, [slashMenu.query, slashMenu.visible])

  useEffect(() => {
    if (!slashMenu.visible) return
    slashMenuRef.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [slashMenu.visible, slashSelectedIndex])

  useEffect(() => {
    const element = dialogRef.current
    if (!element) return
    return dropTargetForExternal({
      element,
      canDrop: containsFiles,
      onDrop: ({ source }) => attachFiles(getFiles({ source }), editor),
    })
  }, [attachFiles, editor])

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    attachFiles(Array.from(event.target.files ?? []), editor)
    event.target.value = ''
  }

  if (typeof document === 'undefined') return null

  const activeSlashIndex = Math.min(slashSelectedIndex, Math.max(0, slashItems.length - 1))

  return createPortal(
    <>
      <div className={styles.addCardBackdrop} onClick={onClose} />
      <div ref={dialogRef} className={styles.dialog} role="dialog" aria-modal="true" aria-label="Новая заметка">
        <div className={styles.addCardEditorShell}>
          <div className={styles.addCardKicker}>Новая заметка</div>
          {editor && <BubbleTools editor={editor} onLink={() => promptLink(editor)} />}
          <EditorContent editor={editor} className={styles.quickNoteEditor} />
          {slashMenu.visible && slashItems.length > 0 && editor && (
            <div
              ref={slashMenuRef}
              className={styles.quickNoteSlashMenu}
              style={{ top: slashMenu.top, left: slashMenu.left }}
              role="listbox"
              aria-label="Команды редактора"
            >
              {slashItems.map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  className={index === activeSlashIndex ? styles.quickNoteSlashItemActive : ''}
                  data-active={index === activeSlashIndex ? 'true' : undefined}
                  role="option"
                  aria-selected={index === activeSlashIndex}
                  onMouseEnter={() => setSlashSelectedIndex(index)}
                  onMouseDown={event => {
                    event.preventDefault()
                    runSlashCommand(editor, item.id, pickImage)
                    setSlashMenu(HIDDEN_SLASH_MENU)
                  }}
                >
                  {item.icon}
                  <span className={styles.quickNoteSlashText}>
                    <span>{item.label}</span>
                    <small>{item.description}</small>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        {files.length > 0 && (
          <ul className={styles.addCardFileList}>
            {files.map((file, index) => (
              <li key={`${file.name}-${index}`} className={styles.addCardFileItem}>
                <span className={styles.addCardFileName}>{file.name}</span>
                <button
                  type="button"
                  className={styles.addCardFileRemove}
                  aria-label={`Убрать ${file.name}`}
                  onClick={() => setFiles(prev => prev.filter((_, i) => i !== index))}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className={styles.addCardActions}>
          <label className={styles.addCardFileBtn} title="Прикрепить файл">
            <Paperclip size={15} />
            <input ref={fileInputRef} type="file" multiple hidden onChange={handleFileChange} />
          </label>
          <button type="button" className={styles.addCardCancelBtn} onClick={onClose}>Отмена</button>
          <button
            type="button"
            className={styles.addCardSubmitBtn}
            disabled={isEditorEmpty && files.length === 0}
            onClick={submit}
          >
            Создать
          </button>
        </div>
      </div>
    </>,
    document.body,
  )
}
