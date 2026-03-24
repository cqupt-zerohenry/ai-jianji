/**
 * MultiTimeline — the full multi-track timeline editing area.
 * Wraps DnD provider and renders all timeline tracks.
 * Ruler and tracks share synced horizontal scroll.
 */
import React from 'react'
import { DndProvider } from 'react-dnd'
import { HTML5Backend } from 'react-dnd-html5-backend'
import { Plus, Layers } from 'lucide-react'
import { TimelineTrack } from './TimelineTrack'
import { TIMELINE_PX_PER_SECOND } from '@/utils/constants'
import { formatSeconds } from '@/utils/time'
import type { Timeline } from '@/types'

interface MultiTimelineProps {
  timelines: Timeline[]
  selectedClipId: string | null
  selectedTimelineId: string | null
  onSelectClip: (clipId: string | null, timelineId: string) => void
  onMoveClip: (fromTlId: string, toTlId: string, clipId: string, toIndex: number) => void
  onDeleteClip: (timelineId: string, clipId: string) => void
  onAddClip: (timelineId: string) => void
  onAddTimeline: () => void
  onDeleteTimeline: (timelineId: string) => void
  onRenameTimeline: (timelineId: string, name: string) => void
  onSeekSource?: (timelineId: string, time: number) => void
  onRulerSeek?: (seconds: number) => void
  playheadSeconds?: number
}

export function MultiTimeline({
  timelines,
  selectedClipId,
  selectedTimelineId,
  onSelectClip,
  onMoveClip,
  onDeleteClip,
  onAddClip,
  onAddTimeline,
  onDeleteTimeline,
  onRenameTimeline,
  onSeekSource,
  onRulerSeek,
  playheadSeconds = 0,
}: MultiTimelineProps) {
  const rulerScrollRef = React.useRef<HTMLDivElement>(null)
  const tracksScrollRef = React.useRef<HTMLDivElement>(null)
  const syncingRef = React.useRef(false)

  const getTrackDuration = React.useCallback((timeline: Timeline): number => {
    const sorted = [...timeline.clips].sort((a, b) => a.order_index - b.order_index)
    if ((timeline.name || '').startsWith('Source:')) {
      return sorted.reduce((max, c) => Math.max(max, c.end_time), 0)
    }
    return sorted.reduce((sum, c) => sum + Math.max(0, c.end_time - c.start_time), 0)
  }, [])

  const maxClipEndSeconds = React.useMemo(
    () => timelines.reduce((max, t) => Math.max(max, getTrackDuration(t)), 0),
    [getTrackDuration, timelines],
  )
  const timelineDurationSeconds = Math.max(60, playheadSeconds, maxClipEndSeconds)

  // Sync horizontal scroll between ruler and tracks
  const handleTracksScroll = React.useCallback(() => {
    if (syncingRef.current) return
    const tracks = tracksScrollRef.current
    const ruler = rulerScrollRef.current
    if (tracks && ruler) {
      syncingRef.current = true
      ruler.scrollLeft = tracks.scrollLeft
      syncingRef.current = false
    }
  }, [])

  const handleRulerScroll = React.useCallback(() => {
    if (syncingRef.current) return
    const tracks = tracksScrollRef.current
    const ruler = rulerScrollRef.current
    if (tracks && ruler) {
      syncingRef.current = true
      tracks.scrollLeft = ruler.scrollLeft
      syncingRef.current = false
    }
  }, [])

  return (
    <DndProvider backend={HTML5Backend}>
      <div className="flex flex-col h-full bg-gray-900 rounded-md border border-gray-700 overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-gray-400" />
            <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">
              Timeline Editor
            </span>
            <span className="text-xs text-gray-500">({timelines.length} tracks)</span>
          </div>
          <button
            onClick={onAddTimeline}
            className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            <Plus className="w-3 h-3" />
            Add Track
          </button>
        </div>

        {/* Timeline ruler — scrolls in sync with tracks */}
        <TimelineRuler
          ref={rulerScrollRef}
          playheadSeconds={playheadSeconds}
          timelineDurationSeconds={timelineDurationSeconds}
          onSeek={onRulerSeek}
          onScroll={handleRulerScroll}
        />

        {/* Tracks — scrolls in sync with ruler */}
        <div
          ref={tracksScrollRef}
          className="flex-1 overflow-y-auto overflow-x-auto"
          onScroll={handleTracksScroll}
        >
          {timelines.length === 0 ? (
            <div className="flex items-center justify-center h-24 text-gray-600 text-sm">
              No timelines — click "Add Track" or load a job
            </div>
          ) : (
            [...timelines]
              .sort((a, b) => a.order_index - b.order_index)
              .map(tl => (
                <TimelineTrack
                  key={tl.id}
                  timeline={tl}
                  selectedClipId={tl.id === selectedTimelineId ? selectedClipId : null}
                  onSelectClip={onSelectClip}
                  onMoveClip={onMoveClip}
                  onDeleteClip={onDeleteClip}
                  onAddClip={onAddClip}
                  onDeleteTimeline={onDeleteTimeline}
                  onRenameTimeline={onRenameTimeline}
                  onSeekSource={onSeekSource}
                  allTimelines={timelines}
                  playheadSeconds={playheadSeconds}
                  timelineDurationSeconds={timelineDurationSeconds}
                />
              ))
          )}
        </div>
      </div>
    </DndProvider>
  )
}

interface TimelineRulerProps {
  playheadSeconds?: number
  timelineDurationSeconds: number
  onSeek?: (seconds: number) => void
  onScroll?: () => void
}

const TimelineRuler = React.forwardRef<HTMLDivElement, TimelineRulerProps>(
  function TimelineRuler(
    { playheadSeconds = 0, timelineDurationSeconds, onSeek, onScroll },
    ref,
  ) {
    const innerRef = React.useRef<HTMLDivElement>(null)
    const draggingRef = React.useRef(false)

    const tickStep =
      timelineDurationSeconds <= 5 * 60 ? 10 :
      timelineDurationSeconds <= 30 * 60 ? 30 :
      60
    const tickCount = Math.ceil(timelineDurationSeconds / tickStep)
    const ticks = Array.from({ length: tickCount + 1 }, (_, i) => i * tickStep)
    const timelineWidthPx = Math.max(1, timelineDurationSeconds * TIMELINE_PX_PER_SECOND)
    const playheadLeftPx = Math.max(0, playheadSeconds) * TIMELINE_PX_PER_SECOND

    const pxToSeconds = React.useCallback((clientX: number) => {
      const el = innerRef.current
      if (!el) return 0
      const rect = el.getBoundingClientRect()
      const x = clientX - rect.left
      return Math.max(0, Math.min(x / TIMELINE_PX_PER_SECOND, timelineDurationSeconds))
    }, [timelineDurationSeconds])

    const handleMouseDown = React.useCallback((e: React.MouseEvent) => {
      if (!onSeek) return
      if (e.button !== 0) return
      e.preventDefault()
      draggingRef.current = true
      onSeek(pxToSeconds(e.clientX))

      const handleMouseMove = (me: MouseEvent) => {
        if (!draggingRef.current) return
        onSeek(pxToSeconds(me.clientX))
      }

      const handleMouseUp = () => {
        draggingRef.current = false
        window.removeEventListener('mousemove', handleMouseMove)
        window.removeEventListener('mouseup', handleMouseUp)
      }

      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
    }, [onSeek, pxToSeconds])

    return (
      <div
        ref={ref}
        className="flex h-6 bg-gray-800 border-b border-gray-700 overflow-x-auto overflow-y-hidden"
        style={{ scrollbarWidth: 'none' }}
        onScroll={onScroll}
      >
        <div className="w-40 flex-shrink-0 border-r border-gray-700 flex items-center px-2 sticky left-0 z-10 bg-gray-800">
          <span className="text-[9px] text-gray-500 font-mono">
            {formatSeconds(Math.max(0, playheadSeconds))}
          </span>
        </div>
        <div
          ref={innerRef}
          className={`relative flex items-end ${onSeek ? 'cursor-pointer' : ''}`}
          style={{ width: `${timelineWidthPx}px`, minWidth: `${timelineWidthPx}px` }}
          onMouseDown={handleMouseDown}
        >
          {/* Playhead line */}
          <div
            className="absolute top-0 bottom-0 w-px bg-rose-400 z-20 pointer-events-none"
            style={{ left: `${playheadLeftPx}px` }}
          />
          {/* Playhead handle */}
          <div
            className={`absolute top-0 z-20 -translate-x-1/2 ${onSeek ? 'cursor-grab active:cursor-grabbing' : 'pointer-events-none'}`}
            style={{ left: `${playheadLeftPx}px` }}
          >
            <div className="w-2.5 h-3 bg-rose-500 rounded-b-sm" style={{ clipPath: 'polygon(0 0, 100% 0, 100% 60%, 50% 100%, 0 60%)' }} />
          </div>
          {ticks.map(sec => {
            const left = sec * TIMELINE_PX_PER_SECOND
            const isMinute = sec % 60 === 0
            return (
              <div
                key={sec}
                className="absolute bottom-0 flex flex-col items-center pointer-events-none"
                style={{ left: `${left}px` }}
              >
                <div className={`w-px ${isMinute ? 'h-3 bg-gray-500' : 'h-2 bg-gray-600'}`} />
                {isMinute && (
                  <span className="absolute bottom-3 text-[9px] text-gray-500 -translate-x-1/2">
                    {sec / 60}m
                  </span>
                )}
              </div>
            )
          })}
        </div>
      </div>
    )
  }
)
