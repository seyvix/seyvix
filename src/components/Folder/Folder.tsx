import { useState } from 'react'
import './Folder.css'

const darkenColor = (hex: string, percent: number): string => {
  let color = hex.startsWith('#') ? hex.slice(1) : hex
  if (color.length === 3) color = color.split('').map(c => c + c).join('')
  const num = parseInt(color, 16)
  let r = (num >> 16) & 0xff
  let g = (num >> 8) & 0xff
  let b = num & 0xff
  r = Math.max(0, Math.min(255, Math.floor(r * (1 - percent))))
  g = Math.max(0, Math.min(255, Math.floor(g * (1 - percent))))
  b = Math.max(0, Math.min(255, Math.floor(b * (1 - percent))))
  return '#' + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1).toUpperCase()
}

interface FolderProps {
  color?: string
  size?: number
  items?: React.ReactNode[]
  paperColors?: string[]
  maxItems?: number
  open?: boolean
  onFolderClick?: () => void
  onPaperClick?: (index: number) => void
}

export default function Folder({
  color = '#6366f1',
  size = 1,
  items = [],
  paperColors,
  maxItems = 3,
  open: openProp,
  onFolderClick,
  onPaperClick,
}: FolderProps) {
  const [openInner, setOpenInner] = useState(false)
  const open = openProp !== undefined ? openProp : openInner
  const papers = items.slice(0, maxItems)
  while (papers.length < maxItems) papers.push(null)

  const folderBackColor = darkenColor(color, 0.08)
  const paper1 = paperColors?.[0] ?? darkenColor('#ffffff', 0.1)
  const paper2 = paperColors?.[1] ?? darkenColor('#ffffff', 0.05)
  const paper3 = paperColors?.[2] ?? '#ffffff'

  const handleFolderClick = () => {
    if (openProp === undefined) setOpenInner(p => !p)
    onFolderClick?.()
  }

  const handlePaperClick = (e: React.MouseEvent, index: number) => {
    e.stopPropagation()
    onPaperClick?.(index)
  }

  const folderStyle = {
    '--folder-color':      color,
    '--folder-back-color': folderBackColor,
    '--paper-1':           paper1,
    '--paper-2':           paper2,
    '--paper-3':           paper3,
  } as React.CSSProperties

  return (
    <div style={{ transform: `scale(${size})` }}>
      <div
        className={`folder ${open ? 'open' : ''}`}
        style={{ ...folderStyle, cursor: onFolderClick ? 'pointer' : 'default' }}
        onClick={onFolderClick ? handleFolderClick : undefined}
      >
        <div className="folder__back">
          {papers.map((item, i) => (
            <div
              key={i}
              className={`paper paper-${i + 1}`}
              onClick={e => handlePaperClick(e, i)}
            >
              {item}
            </div>
          ))}
          <div className="folder__front" />
          <div className="folder__front right" />
        </div>
      </div>
    </div>
  )
}
