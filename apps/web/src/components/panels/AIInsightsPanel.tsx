/**
 * AIInsightsPanel — shows AI detection results, event list, and clip plan.
 */
import React, { useState } from 'react'
import { Brain, ChevronDown, ChevronRight, Zap } from 'lucide-react'
import { EVENT_TYPE_COLORS, EVENT_TYPE_LABELS } from '@/utils/constants'
import { formatSeconds, formatDuration } from '@/utils/time'
import type { JobDetail, DetectedEvent } from '@/types'

interface AIInsightsPanelProps {
  job: JobDetail
}

export function AIInsightsPanel({ job }: AIInsightsPanelProps) {
  const [expanded, setExpanded] = useState<'events' | 'plan' | null>('events')
  const sortedPlanClips = React.useMemo(() => {
    if (!job.ai_plan?.clips) return []
    return [...job.ai_plan.clips].sort((a, b) => {
      if (a.start_time !== b.start_time) return a.start_time - b.start_time
      return a.order_index - b.order_index
    })
  }, [job.ai_plan?.clips])

  return (
    <div className="flex flex-col h-full text-xs">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-800 border-b border-gray-700">
        <Brain className="w-4 h-4 text-purple-400" />
        <span className="font-semibold text-gray-200 uppercase tracking-wider">AI Analysis</span>
        {job.detection_chain && (
          <span className="ml-auto px-1.5 py-0.5 rounded text-[10px] bg-purple-900/50 text-purple-300">
            {job.detection_chain}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Summary */}
        {job.ai_plan && (
          <div className="p-3 border-b border-gray-700">
            <div className="flex items-start gap-2">
              <Zap className="w-3.5 h-3.5 text-yellow-400 mt-0.5 flex-shrink-0" />
              <p className="text-gray-300 leading-relaxed">{job.ai_plan.ai_summary}</p>
            </div>
          </div>
        )}

        {/* Events section */}
        <div>
          <button
            className="w-full flex items-center gap-2 px-3 py-2 text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
            onClick={() => setExpanded(e => e === 'events' ? null : 'events')}
          >
            {expanded === 'events' ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
            <span className="font-medium">Detected Events</span>
            <span className="ml-auto text-gray-500">({job.events.length})</span>
          </button>

          {expanded === 'events' && (
            <div className="divide-y divide-gray-800">
              {job.events.length === 0 ? (
                <div className="px-3 py-4 text-center text-gray-600">
                  No events detected yet
                </div>
              ) : (
                [...job.events]
                  .sort((a, b) => a.timestamp_seconds - b.timestamp_seconds)
                  .map(event => (
                    <EventRow key={event.id} event={event} />
                  ))
              )}
            </div>
          )}
        </div>

        {/* Clip plan section */}
        {job.ai_plan && (
          <div>
            <button
              className="w-full flex items-center gap-2 px-3 py-2 text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
              onClick={() => setExpanded(e => e === 'plan' ? null : 'plan')}
            >
              {expanded === 'plan' ? (
                <ChevronDown className="w-3 h-3" />
              ) : (
                <ChevronRight className="w-3 h-3" />
              )}
              <span className="font-medium">Clip Plan</span>
              <span className="ml-auto text-gray-500">({job.ai_plan.clips.length} clips)</span>
            </button>

            {expanded === 'plan' && (
              <div className="divide-y divide-gray-800">
                {sortedPlanClips.map((clip, i) => (
                  <div key={i} className="px-3 py-2 flex items-center gap-2">
                    <span className="text-gray-600 w-4 text-right">{i + 1}.</span>
                    <div
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: EVENT_TYPE_COLORS[clip.event_type] ?? '#6b7280' }}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-gray-300 truncate">{EVENT_TYPE_LABELS[clip.event_type] ?? clip.event_type}</div>
                      <div className="text-gray-500">
                        {formatSeconds(clip.start_time)} → {formatSeconds(clip.end_time)}
                        {' '}({formatDuration(clip.end_time - clip.start_time)})
                      </div>
                    </div>
                    <div className="text-gray-600 text-[10px]">
                      {clip.transition_type}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function EventRow({ event }: { event: DetectedEvent }) {
  const color = EVENT_TYPE_COLORS[event.event_type] ?? '#6b7280'
  return (
    <div className="flex items-center gap-2 px-3 py-2 hover:bg-gray-800/50 transition-colors">
      <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
      <span className="font-mono text-gray-400 w-12 flex-shrink-0">
        {formatSeconds(event.timestamp_seconds)}
      </span>
      <span className="font-medium" style={{ color }}>
        {EVENT_TYPE_LABELS[event.event_type] ?? event.event_type}
      </span>
      {event.description && (
        <span className="text-gray-500 truncate flex-1">{event.description}</span>
      )}
      <span className="text-gray-600 flex-shrink-0">
        {Math.round(event.confidence * 100)}%
      </span>
    </div>
  )
}
