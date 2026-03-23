/**
 * ClipInspector — edits selected clip properties (in/out points, transition, title).
 */
import React, { useState, useEffect } from 'react'
import { X, Scissors } from 'lucide-react'
import { EVENT_TYPE_LABELS, TRANSITION_TYPE_LABELS } from '@/utils/constants'
import { resolveEventType } from '@/utils/eventType'
import { formatSeconds, parseTimeInput } from '@/utils/time'
import type { Clip, TransitionType } from '@/types'

interface ClipInspectorProps {
  clip: Clip | null
  timelineId: string | null
  onUpdate: (timelineId: string, clipId: string, patch: Partial<Clip>) => void
  onDelete: (timelineId: string, clipId: string) => void
  readOnly?: boolean
}

export function ClipInspector({
  clip, timelineId, onUpdate, onDelete, readOnly = false,
}: ClipInspectorProps) {
  const [startInput, setStartInput] = useState('')
  const [endInput, setEndInput] = useState('')
  const [title, setTitle] = useState('')

  useEffect(() => {
    if (!clip) return
    setStartInput(formatSeconds(clip.start_time))
    setEndInput(formatSeconds(clip.end_time))
    setTitle(clip.title)
  }, [clip?.id])

  if (!clip || !timelineId) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600 text-sm px-4 text-center">
        <div>
          <Scissors className="w-6 h-6 mx-auto mb-2 opacity-40" />
          Select a clip to edit its properties
        </div>
      </div>
    )
  }

  const duration = clip.end_time - clip.start_time
  const resolvedEventType = resolveEventType(clip.event_type, clip.title)

  const applyStart = () => {
    const v = parseTimeInput(startInput)
    if (!isNaN(v) && v < clip.end_time) {
      onUpdate(timelineId, clip.id, { start_time: v })
    } else {
      setStartInput(formatSeconds(clip.start_time))
    }
  }

  const applyEnd = () => {
    const v = parseTimeInput(endInput)
    if (!isNaN(v) && v > clip.start_time) {
      onUpdate(timelineId, clip.id, { end_time: v })
    } else {
      setEndInput(formatSeconds(clip.end_time))
    }
  }

  const applyTitle = () => onUpdate(timelineId, clip.id, { title })

  return (
    <div className="flex flex-col gap-3 p-3 text-xs">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-gray-200 text-sm">Clip Inspector</span>
        {!readOnly && (
          <button
            onClick={() => onDelete(timelineId, clip.id)}
            className="text-gray-500 hover:text-red-400 transition-colors"
            title="Delete clip"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {readOnly && (
        <div className="rounded border border-blue-900/50 bg-blue-950/20 px-2 py-1.5 text-[10px] text-blue-200">
          Source reference clip (read-only). Click source tracks to sync Source Monitor.
        </div>
      )}

      {/* Title */}
      <div>
        <label className="text-gray-400 block mb-1">Title</label>
        <input
          className="w-full bg-gray-700 text-white rounded px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-blue-500"
          value={title}
          disabled={readOnly}
          onChange={e => setTitle(e.target.value)}
          onBlur={applyTitle}
          onKeyDown={e => e.key === 'Enter' && applyTitle()}
        />
      </div>

      {/* In/Out points */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-gray-400 block mb-1">In Point</label>
          <input
            className="w-full bg-gray-700 text-white rounded px-2 py-1 text-xs font-mono outline-none focus:ring-1 focus:ring-blue-500"
            value={startInput}
            disabled={readOnly}
            onChange={e => setStartInput(e.target.value)}
            onBlur={applyStart}
            onKeyDown={e => e.key === 'Enter' && applyStart()}
          />
        </div>
        <div>
          <label className="text-gray-400 block mb-1">Out Point</label>
          <input
            className="w-full bg-gray-700 text-white rounded px-2 py-1 text-xs font-mono outline-none focus:ring-1 focus:ring-blue-500"
            value={endInput}
            disabled={readOnly}
            onChange={e => setEndInput(e.target.value)}
            onBlur={applyEnd}
            onKeyDown={e => e.key === 'Enter' && applyEnd()}
          />
        </div>
      </div>

      <div className="text-gray-500">Duration: {formatSeconds(duration)}</div>
      {!readOnly && (
        <div className="text-[10px] text-gray-500">
          Edits auto-snap near neighboring boundaries and prevent overlaps.
        </div>
      )}

      {/* Transition */}
      <div>
        <label className="text-gray-400 block mb-1">Transition to Next</label>
        <select
          className="w-full bg-gray-700 text-white rounded px-2 py-1 text-xs outline-none"
          value={clip.transition_type}
          disabled={readOnly}
          onChange={e => onUpdate(timelineId, clip.id, {
            transition_type: e.target.value as TransitionType
          })}
        >
          {Object.entries(TRANSITION_TYPE_LABELS).map(([val, label]) => (
            <option key={val} value={val}>{label}</option>
          ))}
        </select>
      </div>

      {clip.transition_type !== 'cut' && (
        <div>
          <label className="text-gray-400 block mb-1">
            Transition Duration: {clip.transition_duration}s
          </label>
          <input
            type="range" min="0.1" max="2" step="0.1"
            value={clip.transition_duration}
            disabled={readOnly}
            onChange={e => onUpdate(timelineId, clip.id, {
              transition_duration: parseFloat(e.target.value)
            })}
            className="w-full accent-blue-500"
          />
        </div>
      )}

      {/* Meta */}
      <div className="pt-2 border-t border-gray-700 space-y-1 text-gray-500">
        {resolvedEventType && (
          <div>
            事件: <span className="text-gray-300">{EVENT_TYPE_LABELS[resolvedEventType] ?? resolvedEventType}</span>
          </div>
        )}
        <div>Source: <span className="text-gray-300">{clip.is_ai_generated ? 'AI Generated' : 'Manual'}</span></div>
      </div>
    </div>
  )
}
