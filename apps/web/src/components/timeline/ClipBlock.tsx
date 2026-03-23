/**
 * ClipBlock — a single clip on the timeline track.
 * Draggable, selectable, shows event type color.
 */
import React, { useRef } from 'react'
import { useDrag, useDrop } from 'react-dnd'
import { X } from 'lucide-react'
import { EVENT_TYPE_COLORS, EVENT_TYPE_LABELS, TIMELINE_PX_PER_SECOND } from '@/utils/constants'
import { resolveEventType } from '@/utils/eventType'
import { formatSeconds } from '@/utils/time'
import type { Clip } from '@/types'

const DND_TYPE = 'CLIP'

interface ClipBlockProps {
  clip: Clip
  timelineId: string
  isSelected: boolean
  onSelect: () => void
  onMoveClip: (fromTlId: string, toTlId: string, clipId: string, toIndex: number) => void
  index: number
  draggable?: boolean
  onDelete?: () => void
  overlays?: { start: number; end: number; label?: string }[]
}

export function ClipBlock({
  clip,
  timelineId,
  isSelected,
  onSelect,
  onMoveClip,
  index,
  draggable = true,
  onDelete,
  overlays = [],
}: ClipBlockProps) {
  const ref = useRef<HTMLDivElement>(null)
  const duration = clip.end_time - clip.start_time
  const width = Math.max(6, duration * TIMELINE_PX_PER_SECOND)
  const resolvedEventType = resolveEventType(clip.event_type, clip.title)
  const color = resolvedEventType ? EVENT_TYPE_COLORS[resolvedEventType] ?? '#4b5563' : '#4b5563'
  const eventLabel = resolvedEventType ? EVENT_TYPE_LABELS[resolvedEventType] ?? resolvedEventType : ''
  const displayTitle = clip.is_ai_generated && eventLabel
    ? eventLabel
    : (clip.title || eventLabel || '片段')
  const totalDuration = Math.max(0.0001, duration)

  const [{ isDragging }, drag] = useDrag({
    type: DND_TYPE,
    canDrag: draggable,
    item: { clipId: clip.id, timelineId, index },
    collect: monitor => ({ isDragging: monitor.isDragging() }),
  })

  const [{ isOver }, drop] = useDrop({
    accept: DND_TYPE,
    canDrop: () => draggable,
    hover(item: { clipId: string; timelineId: string; index: number }) {
      if (!draggable) return
      if (item.clipId === clip.id) return
      onMoveClip(item.timelineId, timelineId, item.clipId, index)
      item.timelineId = timelineId
      item.index = index
    },
    collect: monitor => ({ isOver: monitor.isOver() }),
  })

  if (draggable) {
    drag(drop(ref))
  } else {
    drop(ref)
  }

  return (
    <div
      ref={ref}
      onClick={(e) => { e.stopPropagation(); onSelect() }}
      className={`
        relative inline-flex flex-col justify-between h-14 rounded cursor-pointer
        border-2 select-none overflow-hidden transition-all
        ${isSelected ? 'border-white shadow-lg shadow-blue-500/30 scale-[1.02]' : 'border-transparent hover:border-gray-500'}
        ${isDragging ? 'opacity-50' : 'opacity-100'}
        ${isOver ? 'ring-2 ring-blue-400' : ''}
      `}
      style={{ width: `${width}px`, minWidth: `${width}px`, backgroundColor: color + '33', borderColor: isSelected ? '#fff' : color }}
      title={`${displayTitle}\n${formatSeconds(clip.start_time)} → ${formatSeconds(clip.end_time)}`}
    >
      {/* Top color bar */}
      <div className="h-1 w-full" style={{ backgroundColor: color }} />

      {onDelete && (
        <button
          className="absolute right-1 top-1 z-30 rounded bg-black/45 p-0.5 text-gray-200 hover:bg-red-500/80 hover:text-white"
          onClick={(e) => {
            e.stopPropagation()
            onDelete()
          }}
          title="删除片段"
        >
          <X className="w-2.5 h-2.5" />
        </button>
      )}

      {overlays.length > 0 && (
        <div className="absolute left-0 right-0 top-1 h-2 pointer-events-none">
          {overlays.map((m, i) => {
            const leftPct = Math.max(0, Math.min(100, ((m.start - clip.start_time) / totalDuration) * 100))
            const rightPct = Math.max(0, Math.min(100, ((m.end - clip.start_time) / totalDuration) * 100))
            const widthPct = Math.max(1, rightPct - leftPct)
            return (
              <div
                key={`${i}_${m.start}_${m.end}`}
                className="absolute h-full rounded-sm bg-emerald-400/70 border border-emerald-200/70"
                style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                title={m.label || 'Used in AI track'}
              />
            )
          })}
        </div>
      )}

      {/* Content */}
      <div className="px-1.5 py-0.5 flex flex-col mt-1">
        <span className="text-[10px] font-semibold text-white truncate leading-tight">
          {displayTitle}
        </span>
        <span className="text-[9px] text-gray-300 leading-tight">
          {formatSeconds(clip.start_time)} – {formatSeconds(clip.end_time)}
        </span>
      </div>

      {/* Transition indicator */}
      {clip.transition_type !== 'cut' && (
        <div className="absolute right-0 top-0 bottom-0 w-2 flex items-center justify-center"
          style={{ backgroundColor: color + '88' }}>
          <div className="w-0.5 h-full bg-white/50" />
        </div>
      )}
    </div>
  )
}
