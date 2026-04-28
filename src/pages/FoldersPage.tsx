import { useNavigate } from 'react-router-dom'
import { noteFixtures } from '../mocks/fixtures/notes'
import { folderFixtures } from '../mocks/fixtures/folders'

// ─── Layout constants ─────────────────────────────────────────────────────────

const ROOT = { x: 520, y: 370 }
const NODE_H = 36

// ─── Tag groups ───────────────────────────────────────────────────────────────

const TAG_GROUPS = [
  { label: 'JavaScript', color: '#facc15', tags: ['js', 'mdn', 'web-api', 'html'],        gy: 55  },
  { label: 'CSS',        color: '#38bdf8', tags: ['css', 'animation', 'frontend'],         gy: 165 },
  { label: 'Фреймворки', color: '#818cf8', tags: ['react', 'typescript', 'performance'],   gy: 265 },
  { label: 'Бэкенд',    color: '#4ade80', tags: ['backend', 'db', 'arch'],                gy: 365 },
  { label: 'Дизайн',    color: '#f472b6', tags: ['design', 'links', 'ref'],               gy: 455 },
  { label: 'Инструменты',color: '#fb923c', tags: ['tools', 'productivity', 'editor'],      gy: 550 },
  { label: 'Личное',    color: '#c084fc', tags: ['books', 'learning', 'photo', 'travel'],  gy: 650 },
]

const GROUP_X  = 810   // x-center of group nodes
const LEAF_X   = 1060  // x-center of leaf (tag) nodes
const LEAF_GAP = 38    // vertical gap between leaves in a group

// Left side — folders
const FOLDERS_HUB_X = 240
const FOLDER_X      = 60
const SUBFOLDER_X   = -130

// ─── Helpers ──────────────────────────────────────────────────────────────────

function tagCount(name: string) {
  return noteFixtures.filter(n => n.tags.some(t => t.name === name)).length
}

function folderCount(id: string) {
  return noteFixtures.filter(n => n.folderId === id).length
}

/** Cubic bezier path between two centre points (horizontal tangents). */
function bezier(x1: number, y1: number, x2: number, y2: number) {
  const mx = (x1 + x2) / 2
  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`
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
  x, y, label, count, color, onClick,
}: { x: number; y: number; label: string; count: number; color: string; onClick?: () => void }) {
  const w = 130
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
      <text x={x - 10} y={y + 5} textAnchor="end" fill="#c9c9e0" fontSize={11}>
        {label}
      </text>
      <text x={x + 14} y={y + 5} textAnchor="start" fill={color} fontSize={10} fontWeight={600}>
        {count}
      </text>
    </g>
  )
}

function FolderNode({
  x, y, label, count, onClick,
}: { x: number; y: number; label: string; count: number; onClick?: () => void }) {
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
      <text x={x - 8} y={y + 5} textAnchor="end" fill="#a5b4fc" fontSize={11}>
        {label}
      </text>
      <text x={x + 12} y={y + 5} textAnchor="start" fill="#6366f1" fontSize={10} fontWeight={600}>
        {count}
      </text>
    </g>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function FoldersPage() {
  const navigate = useNavigate()

  // Build leaf positions for each tag group
  const groups = TAG_GROUPS.map(g => {
    const total = g.tags.length
    const startY = g.gy - ((total - 1) * LEAF_GAP) / 2
    const leaves = g.tags.map((tag, i) => ({ tag, y: startY + i * LEAF_GAP }))
    return { ...g, leaves }
  })

  // Folder layout
  const folderHubY = ROOT.y
  const f1 = folderFixtures[0] // Engineering
  const f2 = folderFixtures[1] // Design
  const f1y = 230
  const f2y = 510

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

        {/* ── Edges (drawn first, under nodes) ──────────────────────────── */}

        {/* Root → folders hub */}
        <Edge x1={ROOT.x - 85} y1={ROOT.y} x2={FOLDERS_HUB_X + 74} y2={folderHubY} color="#6366f1" width={2} />

        {/* Folders hub → top-level folders */}
        <Edge x1={FOLDERS_HUB_X - 74} y1={folderHubY} x2={FOLDER_X + 74} y2={f1y} color="#6366f155" width={1.6} />
        <Edge x1={FOLDERS_HUB_X - 74} y1={folderHubY} x2={FOLDER_X + 74} y2={f2y} color="#6366f155" width={1.6} />

        {/* Engineering → sub-folders */}
        {f1.children.map((child, i) => {
          const cy = f1y - 70 + i * 140
          return (
            <Edge key={child.id}
              x1={FOLDER_X - 74} y1={f1y}
              x2={SUBFOLDER_X + 74} y2={cy}
              color="#6366f133" width={1.3}
            />
          )
        })}

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
              x2={LEAF_X - 65} y2={leaf.y}
              color={g.color} width={1.3}
            />
          ))
        )}

        {/* ── Nodes ─────────────────────────────────────────────────────── */}

        {/* Root */}
        <RootNode x={ROOT.x} y={ROOT.y} label="🧠  База знаний" />

        {/* Folders hub */}
        <CategoryNode x={FOLDERS_HUB_X} y={folderHubY} label="📁  Папки" color="#a5b4fc" />

        {/* Top-level folders */}
        <FolderNode x={FOLDER_X} y={f1y} label={f1.name} count={folderCount(f1.id)}
          onClick={() => navigate(`/folders/${f1.slug}`)} />
        <FolderNode x={FOLDER_X} y={f2y} label={f2.name} count={folderCount(f2.id)}
          onClick={() => navigate(`/folders/${f2.slug}`)} />

        {/* Sub-folders */}
        {f1.children.map((child, i) => {
          const cy = f1y - 70 + i * 140
          return (
            <FolderNode key={child.id} x={SUBFOLDER_X} y={cy}
              label={child.name} count={folderCount(child.id)}
              onClick={() => navigate(`/folders/${child.slug}`)} />
          )
        })}

        {/* Tag group nodes */}
        {groups.map(g => (
          <CategoryNode key={g.label} x={GROUP_X} y={g.gy} label={g.label} color={g.color} />
        ))}

        {/* Tag leaves */}
        {groups.map(g =>
          g.leaves.map(leaf => (
            <LeafNode key={leaf.tag}
              x={LEAF_X} y={leaf.y}
              label={leaf.tag} count={tagCount(leaf.tag)}
              color={g.color}
              onClick={() => navigate(`/notes?tags=${encodeURIComponent(leaf.tag)}`)}
            />
          ))
        )}
      </svg>
    </div>
  )
}
