import { createContext, useContext, useState, useEffect } from 'react'
import { monitorForElements } from '@atlaskit/pragmatic-drag-and-drop/element/adapter'
import { monitorForExternal } from '@atlaskit/pragmatic-drag-and-drop/external/adapter'
import { containsFiles } from '@atlaskit/pragmatic-drag-and-drop/external/file'

interface DragState {
  isDragging: boolean
  draggedId: string | null
  overId: string | null
  setOverId: (id: string | null) => void
  isFileDragging: boolean
}

const DragContext = createContext<DragState>({
  isDragging: false,
  draggedId: null,
  overId: null,
  setOverId: () => {},
  isFileDragging: false,
})

export function DragProvider({ children }: { children: React.ReactNode }) {
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [overId, setOverId] = useState<string | null>(null)
  const [isFileDragging, setIsFileDragging] = useState(false)

  useEffect(() => {
    const cleanupElements = monitorForElements({
      onDragStart: ({ source }) => {
        if (source.data.type === 'note') {
          setDraggedId(source.data.noteId as string)
        }
      },
      onDrop: () => {
        setDraggedId(null)
        setOverId(null)
      },
    })

    const cleanupExternal = monitorForExternal({
      onDragStart: ({ source }) => {
        if (containsFiles({ source })) setIsFileDragging(true)
      },
      onDrop: () => setIsFileDragging(false),
    })

    return () => {
      cleanupElements()
      cleanupExternal()
    }
  }, [])

  return (
    <DragContext.Provider value={{ isDragging: draggedId !== null, draggedId, overId, setOverId, isFileDragging }}>
      {children}
    </DragContext.Provider>
  )
}

export function useDragContext() {
  return useContext(DragContext)
}
