/**
 * TimelineTrack — a single timeline row with drag/drop support.
 */
import React from 'react'
import { useDrop } from 'react-dnd'
import { Trash2, Edit3, Plus } from 'lucide-react'
import { ClipBlock } from './ClipBlock'
import { TIMELINE_PX_PER_SECOND } from '@/utils/constants'
import type { Timeline } from '@/types'

const DND_TYPE = 'CLIP'

interface TimelineTrackProps {
  timeline: Timeline
  selectedClipId: string | null
  onSelectClip: (clipId: string | null, timelineId: string) => void
  onMoveClip: (fromTlId: string, toTlId: string, clipId: string, toIndex: number) => void
  onDeleteClip: (timelineId: string, clipId: string) => void
  onAddClip: (timelineId: string) => void
  onDeleteTimeline: (timelineId: string) => void
  onRenameTimeline: (timelineId: string, name: string) => void
  onSeekSource?: (timelineId: string, time: number) => void
  allTimelines: Timeline[]
  playheadSeconds?: number
  timelineDurationSeconds: number
}

export function TimelineTrack({
  timeline,
  selectedClipId,
  onSelectClip,
  onMoveClip,
  onDeleteClip,
  onAddClip,
  onDeleteTimeline,
  onRenameTimeline,
  onSeekSource,
  allTimelines,
  playheadSeconds,
  timelineDurationSeconds,
}: TimelineTrackProps) {
  const isSourceTrack = timeline.name.startsWith('Source:')
  const isAIGeneratedTrack = timeline.name === 'AI Generated'
  const [editing, setEditing] = React.useState(false)
  const [nameInput, setNameInput] = React.useState(timeline.name)
  const timelineWidthPx = Math.max(1, timelineDurationSeconds * TIMELINE_PX_PER_SECOND)

  const [{ isOver }, drop] = useDrop({
    accept: DND_TYPE,
    canDrop: () => !isSourceTrack,
    drop(item: { clipId: string; timelineId: string; index: number }, monitor) {
      // If a child ClipBlock already handled the drop, skip
      if (monitor.didDrop()) return
      // Append to end of this timeline
      onMoveClip(item.timelineId, timeline.id, item.clipId, timeline.clips.length)
    },
    collect: monitor => ({ isOver: monitor.isOver() }),
  })

  const handleRename = () => {
    onRenameTimeline(timeline.id, nameInput)
    setEditing(false)
  }

  const sourceUsedOverlays = React.useMemo(() => {
    if (!isSourceTrack || timeline.clips.length === 0) return new Map<string, { start: number; end: number; label?: string }[]>()

    const parseJson = (raw?: string): Record<string, unknown> | null => {
      if (!raw) return null
      if (raw.startsWith('source-track:')) {
        const sourcePath = raw.slice('source-track:'.length).trim()
        return sourcePath ? { source_path: sourcePath } : null
      }
      try {
        const obj = JSON.parse(raw)
        return obj && typeof obj === 'object' ? (obj as Record<string, unknown>) : null
      } catch {
        return null
      }
    }

    const overlays = new Map<string, { start: number; end: number; label?: string }[]>()
    for (const sourceClip of timeline.clips) {
      const meta = parseJson(sourceClip.notes)
      const sourceIndex = typeof meta?.source_index === 'number' ? meta.source_index : null
      const sourcePath = typeof meta?.source_path === 'string' ? meta.source_path : null
      const arr: { start: number; end: number; label?: string }[] = []

      if (sourceIndex === null && !sourcePath) {
        overlays.set(sourceClip.id, arr)
        continue
      }

      for (const tl of allTimelines) {
        if (tl.name !== 'AI Generated') continue
        for (const clip of tl.clips) {
          const clipMeta = parseJson(clip.notes)
          if (!clipMeta) continue
          const clipSourceIndex = typeof clipMeta.source_index === 'number' ? clipMeta.source_index : null
          const clipSourcePath = typeof clipMeta.source_path === 'string' ? clipMeta.source_path : null
          const matched =
            (sourceIndex !== null && clipSourceIndex === sourceIndex) ||
            (!!sourcePath && !!clipSourcePath && sourcePath === clipSourcePath)
          if (!matched) continue

          arr.push({
            start: clip.start_time,
            end: clip.end_time,
            label: clip.title,
          })
        }
      }

      overlays.set(sourceClip.id, arr)
    }

    return overlays
  }, [allTimelines, isSourceTrack, timeline.clips])

  const sortedClips = React.useMemo(() => {
    return [...timeline.clips].sort((a, b) => a.order_index - b.order_index)
  }, [timeline.clips])

  const clipLayout = React.useMemo(() => {
    const rows = sortedClips.map((clip, index) => ({
      clip,
      index,
      duration: Math.max(0.0001, clip.end_time - clip.start_time),
      displayStart: 0,
    }))

    if (isSourceTrack) {
      for (const row of rows) {
        row.displayStart = Math.max(0, row.clip.start_time)
      }
      return rows
    }

    let cursor = 0
    for (const row of rows) {
      row.displayStart = cursor
      cursor += row.duration
    }
    return rows
  }, [isSourceTrack, sortedClips])

  const handleTrackClick = (e: React.MouseEvent<HTMLDivElement>) => {
    onSelectClip(null, timeline.id)
    if (!isSourceTrack || !onSeekSource) return

    const rows = clipLayout
    if (!rows.length) return

    const container = e.currentTarget
    const rect = container.getBoundingClientRect()
    const x = e.clientX - rect.left + container.scrollLeft
    const clickedTime = Math.max(0, x / TIMELINE_PX_PER_SECOND)

    const matched = rows.find(r => clickedTime >= r.displayStart && clickedTime <= (r.displayStart + r.duration))
    if (matched) {
      const ratio = Math.max(0, Math.min(1, (clickedTime - matched.displayStart) / matched.duration))
      const seekTime = matched.clip.start_time + ratio * (matched.clip.end_time - matched.clip.start_time)
      onSeekSource(timeline.id, seekTime)
      return
    }

    const maxDisplayEnd = rows[rows.length - 1].displayStart + rows[rows.length - 1].duration
    const clampedDisplayTime = Math.max(0, Math.min(clickedTime, maxDisplayEnd))
    const tail = rows[rows.length - 1]
    const tailRatio = Math.max(0, Math.min(1, (clampedDisplayTime - tail.displayStart) / tail.duration))
    const tailSeek = tail.clip.start_time + tailRatio * (tail.clip.end_time - tail.clip.start_time)
    onSeekSource(timeline.id, tailSeek)
  }

  return (
    <div
      className="flex items-stretch border-b border-gray-700 last:border-b-0 min-h-[72px]"
      style={{ minWidth: `${160 + timelineWidthPx}px` }}
    >
      {/* Track header */}
      <div className="w-40 flex-shrink-0 bg-gray-800 border-r border-gray-700 flex flex-col justify-between px-2 py-1.5">
        {!isSourceTrack && editing ? (
          <input
            className="text-xs text-white bg-gray-700 rounded px-1 py-0.5 outline-none w-full"
            value={nameInput}
            autoFocus
            onChange={e => setNameInput(e.target.value)}
            onBlur={handleRename}
            onKeyDown={e => { if (e.key === 'Enter') handleRename() }}
          />
        ) : (
          <div className="flex items-center gap-1">
            <span className="text-xs text-gray-200 font-medium truncate flex-1">{timeline.name}</span>
            {!isSourceTrack && (
              <>
                <button onClick={() => onAddClip(timeline.id)} className="text-gray-500 hover:text-green-300" title="Add clip">
                  <Plus className="w-3 h-3" />
                </button>
                <button onClick={() => setEditing(true)} className="text-gray-500 hover:text-gray-300">
                  <Edit3 className="w-3 h-3" />
                </button>
              </>
            )}
          </div>
        )}

        <div className="flex items-center gap-1">
          <span className="text-[10px] text-gray-500">{timeline.clips.length} clips</span>
          {!isSourceTrack && (
            <button
              onClick={() => onDeleteTimeline(timeline.id)}
              className="ml-auto text-gray-600 hover:text-red-400 transition-colors"
              title="Delete timeline"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      {/* Clips area */}
      <div
        ref={drop as unknown as React.RefObject<HTMLDivElement>}
        className={`relative flex-1 overflow-hidden transition-colors ${
          isOver ? 'bg-blue-900/20' : 'bg-gray-850'
        } ${isSourceTrack ? 'cursor-pointer' : ''}`}
        style={{ background: isOver ? 'rgba(59,130,246,0.1)' : 'transparent' }}
        onClick={handleTrackClick}
      >
        <div
          className="relative h-full"
          style={{ width: `${timelineWidthPx}px`, minWidth: `${timelineWidthPx}px` }}
        >
          {typeof playheadSeconds === 'number' && playheadSeconds >= 0 && (
            <div
              className="absolute top-0 bottom-0 w-px bg-rose-400/90 pointer-events-none z-20"
              style={{ left: `${Math.max(0, playheadSeconds) * TIMELINE_PX_PER_SECOND}px` }}
            />
          )}
          {clipLayout.map(({ clip, index, displayStart }) => (
            <div
              key={clip.id}
              className="absolute top-1"
              style={{ left: `${Math.max(0, displayStart) * TIMELINE_PX_PER_SECOND}px` }}
            >
            <ClipBlock
              clip={clip}
              timelineId={timeline.id}
              index={index}
              isSelected={clip.id === selectedClipId}
              onSelect={() => {
                onSelectClip(clip.id, timeline.id)
                if (isSourceTrack && onSeekSource) {
                  onSeekSource(timeline.id, clip.start_time)
                }
              }}
              onMoveClip={onMoveClip}
              draggable={!isSourceTrack}
              onDelete={!isSourceTrack ? () => onDeleteClip(timeline.id, clip.id) : undefined}
              overlays={sourceUsedOverlays.get(clip.id) ?? []}
            />
            </div>
          ))}

          {timeline.clips.length === 0 && (
            <div className="text-xs text-gray-600 italic px-2 py-2">
              {isSourceTrack ? 'Source reference track' : 'Drop clips here or add from AI plan'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
