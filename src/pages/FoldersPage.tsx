import { useNavigate } from 'react-router-dom'
import { useFolders } from '../hooks/useFolders'
import type { Folder } from '../types'

// ─── Layout constants ─────────────────────────────────────────────────────────

const ROOT    = { x: 520, y: 370 }
const NODE_H  = 36

// Left side — folders
const FOLDERS_HUB_X = 240
const FOLDER_X      = 60
const SUBFOLDER_X   = -130
const FOLDER_VGAP   = 140   // vertical gap between top-level folders

// Right side — tags
const GROUP_X  = 810
const LEAF_X   = 1060
const LEAF_GAP = 38

// ─── Tag groups (static configuration, no mock counts) ────────────────────────

const TAG_GROUPS = [
  { label: 'JavaScript',  color: '#facc15', tags: ['js', 'mdn', 'web-api', 'html'],        gy: 55  },
  { label: 'CSS',         color: '#38bdf8', tags: ['css', 'animation', 'frontend'],         gy: 165 },
  { label: 'Фреймворки',  color: '#818cf8', tags: ['react', 'typescript', 'performance'],   gy: 265 },
  { label: 'Бэкенд',     color: '#4ade80', tags: ['backend', 'db', 'arch'],                gy: 365 },
  { label: 'Дизайн',     color: '#f472b6', tags: ['design', 'links', 'ref'],               gy: 455 },
  { label: 'Инструменты', color: '#fb923c', tags: ['tools', 'productivity', 'editor'],      gy: 550 },
  { label: 'Личное',     color: '#c084fc', tags: ['books', 'learning', 'photo', 'travel'],  gy: 650 },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Cubic bezier path between two centre points (horizontal tangents). */
function bezier(x1: number, y1: number, x2: number, y2: number) {
  const mx = (x1 + x2) / 2
  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`
}

/**
 * Compute Y positions for a list of top-level folders and their children.
 * All children are spread around their parent's Y.
 */
function layoutFolders(folders: Folder[]) {
  // First pass: compute how much vertical space each top-level folder needs
  const items: Array<{ folder: Folder; y: number; children: Array<{ folder: Folder; y: number }> }> = []
  let cursor = ROOT.y - ((folders.length - 1) * FOLDER_VGAP) / 2

  for (const folder of folders) {
    const childCount  = folder.children.length
    const parentY     = cursor
    const childSpan   = Math.max(childCount - 1, 0) * 80
    const childStartY = parentY - childSpan / 2
    const children    = folder.children.map((child, i) => ({
      folder: child,
      y: childStartY + i * 80,
    }))
    items.push({ folder, y: parentY, children })
    cursor += FOLDER_VGAP
  }

  return items
}

// ─── SVG Primitives ───────────────────────────────────────────────────────────

function Edge({
  x1, y1, x2, y2, color, width = 1.8,
}: { x1: number; y1: number; x2: number; y2: number; color: string; width?: number }) {
  return (
    <path
      d={bezier(x1, y1, x2, y2)}
      fill="none"
      stroke={color}
      strokeWidth={width}
      strokeOpacity={0.6}
    />
  )
}

function RootNode({ x, y, label }: { x: number; y: number; label: string }) {
  const w = 170
  return (
    <g style={{ cursor: 'default' }}>
      <rect
        x={x - w / 2} y={y - NODE_H / 2}
        width={w} height={NODE_H}
        rx={12}
        fill="#6366f1"
        filter="url(#glow-accent)"
      />
      <text x={x} y={y + 5} textAnchor="middle" fill="#fff" fontSize={14} fontWeight={600}>
        {label}
      </text>
    </g>
  )
}

function CategoryNode({
  x, y, label, color, onClick,
}: { x: number; y: number; label: string; color: string; onClick?: () => void }) {
  const w = 148
  return (
    <g onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}>
      <rect
        x={x - w / 2} y={y - NODE_H / 2}
        width={w} height={NODE_H}
        rx={10}
        fill="#18182a"
        stroke={color}
        strokeWidth={1.5}
        strokeOpacity={0.7}
      />
      <text x={x} y={y + 5} textAnchor="middle" fill={color} fontSize={12} fontWeight={600}>
        {label}
      </text>
    </g>
  )
}

function LeafNode({
  x, y, label, color, onClick,
}: { x: number; y: number; label: string; color: string; onClick?: () => void }) {
  const w = 120
  return (
    <g onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}>
      <rect
        x={x - w / 2} y={y - 14}
        width={w} height={28}
        rx={7}
        fill="#111120"
        stroke={color}
        strokeWidth={1}
        strokeOpacity={0.45}
      />
      <text x={x} y={y + 5} textAnchor="middle" fill="#c9c9e0" fontSize={11}>
        {label}
      </text>
    </g>
  )
}

function FolderNode({
  x, y, label, onClick,
}: { x: number; y: number; label: string; onClick?: () => void }) {
  const w = 148
  return (
    <g onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}>
      <rect
        x={x - w / 2} y={y - 14}
        width={w} height={28}
        rx={8}
        fill="#13132a"
        stroke="#6366f1"
        strokeWidth={1}
        strokeOpacity={0.5}
      />
      <text x={x} y={y + 5} textAnchor="middle" fill="#a5b4fc" fontSize={11}>
        {label}
      </text>
    </g>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function FoldersPage() {
  const navigate  = useNavigate()
  const { data: folders = [] } = useFolders()

  const groups      = TAG_GROUPS.map(g => {
    const total  = g.tags.length
    const startY = g.gy - ((total - 1) * LEAF_GAP) / 2
    const leaves = g.tags.map((tag, i) => ({ tag, y: startY + i * LEAF_GAP }))
    return { ...g, leaves }
  })

  const folderItems = layoutFolders(folders)
  const folderHubY  = ROOT.y

  return (
    <div style={{ flex: 1, minHeight: 0, overflow: 'auto', background: '#0f0f0f' }}>
      <svg
        viewBox="-220 0 1450 760"
        width="100%"
        style={{ display: 'block', minHeight: '100%' }}
        fontFamily="-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
      >
        <defs>
          <filter id="glow-accent" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* ── Folder edges ─────────────────────────────────────────────── */}

        {/* Root → folders hub */}
        {folders.length > 0 && (
          <Edge x1={ROOT.x - 85} y1={ROOT.y} x2={FOLDERS_HUB_X + 74} y2={folderHubY} color="#6366f1" width={2} />
        )}

        {/* Folders hub → top-level folders */}
        {folderItems.map(item => (
          <Edge key={item.folder.id}
            x1={FOLDERS_HUB_X - 74} y1={folderHubY}
            x2={FOLDER_X + 74}      y2={item.y}
            color="#6366f155" width={1.6}
          />
        ))}

        {/* Top-level folders → sub-folders */}
        {folderItems.map(item =>
          item.children.map(child => (
            <Edge key={child.folder.id}
              x1={FOLDER_X - 74} y1={item.y}
              x2={SUBFOLDER_X + 74} y2={child.y}
              color="#6366f133" width={1.3}
            />
          ))
        )}

        {/* ── Tag edges ────────────────────────────────────────────────── */}

        {/* Root → tag groups */}
        {groups.map(g => (
          <Edge key={g.label}
            x1={ROOT.x + 85} y1={ROOT.y}
            x2={GROUP_X - 74} y2={g.gy}
            color={g.color} width={2}
          />
        ))}

        {/* Tag groups → leaves */}
        {groups.map(g =>
          g.leaves.map(leaf => (
            <Edge key={leaf.tag}
              x1={GROUP_X + 74} y1={g.gy}
              x2={LEAF_X - 60}  y2={leaf.y}
              color={g.color} width={1.3}
            />
          ))
        )}

        {/* ── Nodes ────────────────────────────────────────────────────── */}

        {/* Root */}
        <RootNode x={ROOT.x} y={ROOT.y} label="🧠  База знаний" />

        {/* Folders hub (only if there are folders) */}
        {folders.length > 0 && (
          <CategoryNode x={FOLDERS_HUB_X} y={folderHubY} label="📁  Папки" color="#a5b4fc" />
        )}

        {/* Top-level folders */}
        {folderItems.map(item => (
          <FolderNode key={item.folder.id}
            x={FOLDER_X} y={item.y}
            label={item.folder.name}
            onClick={() => navigate(`/folders/${item.folder.slug}`)}
          />
        ))}

        {/* Sub-folders */}
        {folderItems.map(item =>
          item.children.map(child => (
            <FolderNode key={child.folder.id}
              x={SUBFOLDER_X} y={child.y}
              label={child.folder.name}
              onClick={() => navigate(`/folders/${child.folder.slug}`)}
            />
          ))
        )}

        {/* Tag group nodes */}
        {groups.map(g => (
          <CategoryNode key={g.label} x={GROUP_X} y={g.gy} label={g.label} color={g.color} />
        ))}

        {/* Tag leaf nodes */}
        {groups.map(g =>
          g.leaves.map(leaf => (
            <LeafNode key={leaf.tag}
              x={LEAF_X} y={leaf.y}
              label={leaf.tag}
              color={g.color}
              onClick={() => navigate(`/notes?tags=${encodeURIComponent(leaf.tag)}`)}
            />
          ))
        )}
      </svg>
    </div>
  )
}
