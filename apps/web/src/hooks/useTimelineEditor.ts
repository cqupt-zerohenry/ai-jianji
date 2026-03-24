/**
 * useTimelineEditor — manages multi-timeline editing state.
 * Wraps immer for immutable updates.
 */
import { useState, useCallback, useEffect, useMemo } from 'react'
import { produce } from 'immer'
import { MIN_CLIP_DURATION, TIMELINE_SNAP_SECONDS } from '@/utils/constants'
import type { Timeline, Clip, RebuildRequest } from '@/types'

export interface TimelineEditorState {
  timelines: Timeline[]
  selectedClipId: string | null
  selectedTimelineId: string | null
}

function sortByOrder(clips: Clip[]): Clip[] {
  return [...clips].sort((a, b) => a.order_index - b.order_index)
}

function buildRebuildFingerprint(timelines: Timeline[]): string {
  const payload = timelines
    .filter(tl => !tl.name.startsWith('Source:'))
    .sort((a, b) => a.order_index - b.order_index)
    .map(tl => ({
      timeline_id: tl.id,
      name: tl.name,
      clips: [...tl.clips]
        .sort((a, b) => a.order_index - b.order_index)
        .map(c => ({
          id: c.id,
          title: c.title,
          event_type: c.event_type ?? null,
          event_id: c.event_id ?? null,
          start_time: Number(c.start_time.toFixed(3)),
          end_time: Number(c.end_time.toFixed(3)),
          transition_type: c.transition_type,
          transition_duration: Number(c.transition_duration.toFixed(3)),
          is_ai_generated: c.is_ai_generated,
          notes: c.notes ?? null,
        })),
    }))
  return JSON.stringify(payload)
}

function getSnapPoints(clips: Clip[], excludeClipId: string): number[] {
  return clips
    .filter(c => c.id !== excludeClipId)
    .flatMap(c => [c.start_time, c.end_time])
}

function snapToNearest(value: number, points: number[], threshold = TIMELINE_SNAP_SECONDS): number {
  if (!points.length) return value
  let best = value
  let bestDistance = Number.POSITIVE_INFINITY
  for (const p of points) {
    const d = Math.abs(value - p)
    if (d <= threshold && d < bestDistance) {
      best = p
      bestDistance = d
    }
  }
  return best
}

function constrainClip(
  sorted: Clip[],
  index: number,
  proposedStart: number,
  proposedEnd: number,
  anchor: 'start' | 'end' | 'both',
): { start: number; end: number } {
  const prev = index > 0 ? sorted[index - 1] : null
  const next = index < sorted.length - 1 ? sorted[index + 1] : null

  const lower = prev ? prev.end_time : 0
  const upper = next ? next.start_time : Number.POSITIVE_INFINITY

  let start = Math.max(proposedStart, lower)
  let end = Number.isFinite(upper) ? Math.min(proposedEnd, upper) : proposedEnd

  if (end - start < MIN_CLIP_DURATION) {
    const available = upper - lower
    if (!Number.isFinite(available) || available >= MIN_CLIP_DURATION) {
      if (anchor === 'start') {
        end = start + MIN_CLIP_DURATION
      } else if (anchor === 'end') {
        start = end - MIN_CLIP_DURATION
      } else {
        end = start + MIN_CLIP_DURATION
      }

      if (Number.isFinite(upper) && end > upper) {
        end = upper
        start = end - MIN_CLIP_DURATION
      }
      if (start < lower) {
        start = lower
        end = start + MIN_CLIP_DURATION
      }
    }
  }

  return { start, end }
}

export function useTimelineEditor(initialTimelines: Timeline[]) {
  const [state, setState] = useState<TimelineEditorState>({
    timelines: initialTimelines,
    selectedClipId: null,
    selectedTimelineId: null,
  })

  // Keep editor state in sync when parent job/timelines change (e.g. switching tasks).
  useEffect(() => {
    setState(prev => {
      const selectedTimelineStillExists = prev.selectedTimelineId
        ? initialTimelines.some(t => t.id === prev.selectedTimelineId)
        : false

      const selectedClipStillExists = (
        selectedTimelineStillExists &&
        prev.selectedClipId &&
        initialTimelines
          .find(t => t.id === prev.selectedTimelineId)
          ?.clips.some(c => c.id === prev.selectedClipId)
      ) || false

      return {
        timelines: initialTimelines,
        selectedTimelineId: selectedTimelineStillExists ? prev.selectedTimelineId : null,
        selectedClipId: selectedClipStillExists ? prev.selectedClipId : null,
      }
    })
  }, [initialTimelines])

  const setTimelines = useCallback((timelines: Timeline[]) => {
    setState(prev => ({ ...prev, timelines }))
  }, [])

  const selectClip = useCallback((clipId: string | null, timelineId: string | null) => {
    setState(prev => ({ ...prev, selectedClipId: clipId, selectedTimelineId: timelineId }))
  }, [])

  const updateClip = useCallback((timelineId: string, clipId: string, patch: Partial<Clip>) => {
    setState(produce(draft => {
      const tl = draft.timelines.find(t => t.id === timelineId)
      if (!tl) return
      const sorted = sortByOrder(tl.clips)
      const idx = sorted.findIndex(c => c.id === clipId)
      if (idx === -1) return

      const clip = sorted[idx]
      const nextValues: Partial<Clip> = { ...patch }

      const hasStartPatch = typeof patch.start_time === 'number'
      const hasEndPatch = typeof patch.end_time === 'number'
      if (hasStartPatch || hasEndPatch) {
        const snapPoints = getSnapPoints(tl.clips, clipId)

        let start = hasStartPatch ? patch.start_time! : clip.start_time
        let end = hasEndPatch ? patch.end_time! : clip.end_time

        if (hasStartPatch) start = snapToNearest(start, snapPoints)
        if (hasEndPatch) end = snapToNearest(end, snapPoints)

        if (end - start < MIN_CLIP_DURATION) {
          if (hasStartPatch && !hasEndPatch) {
            start = end - MIN_CLIP_DURATION
          } else {
            end = start + MIN_CLIP_DURATION
          }
        }

        const anchor: 'start' | 'end' | 'both' =
          hasStartPatch && !hasEndPatch ? 'start' :
          hasEndPatch && !hasStartPatch ? 'end' :
          'both'

        const constrained = constrainClip(sorted, idx, start, end, anchor)
        nextValues.start_time = constrained.start
        nextValues.end_time = constrained.end
      }

      const realClip = tl.clips.find(c => c.id === clipId)
      if (!realClip) return
      Object.assign(realClip, nextValues)
    }))
  }, [])

  const deleteClip = useCallback((timelineId: string, clipId: string) => {
    setState(produce(draft => {
      const tl = draft.timelines.find(t => t.id === timelineId)
      if (!tl) return
      tl.clips = tl.clips.filter(c => c.id !== clipId)
      tl.clips.forEach((c, i) => { c.order_index = i })
      if (draft.selectedTimelineId === timelineId && draft.selectedClipId === clipId) {
        draft.selectedClipId = null
      }
    }))
  }, [])

  const moveClip = useCallback((
    fromTimelineId: string,
    toTimelineId: string,
    clipId: string,
    toIndex: number,
  ) => {
    setState(produce(draft => {
      const fromTl = draft.timelines.find(t => t.id === fromTimelineId)
      const toTl = draft.timelines.find(t => t.id === toTimelineId)
      if (!fromTl || !toTl) return

      const clipIndex = fromTl.clips.findIndex(c => c.id === clipId)
      if (clipIndex === -1) return

      const [clip] = fromTl.clips.splice(clipIndex, 1)
      clip.timeline_id = toTimelineId
      const safeIndex = Math.max(0, Math.min(toIndex, toTl.clips.length))
      toTl.clips.splice(safeIndex, 0, clip)

      fromTl.clips.forEach((c, i) => { c.order_index = i })
      toTl.clips.forEach((c, i) => { c.order_index = i })
    }))
  }, [])

  const addClip = useCallback((
    timelineId: string,
    options?: { startTime?: number; endTime?: number; title?: string },
  ) => {
    const newId = `local_clip_${Date.now()}_${Math.floor(Math.random() * 1000)}`
    setState(produce(draft => {
      const tl = draft.timelines.find(t => t.id === timelineId)
      if (!tl || tl.name.startsWith('Source:')) return

      const sorted = sortByOrder(tl.clips)
      const last = sorted.length ? sorted[sorted.length - 1] : null

      const start = options?.startTime ?? (last ? Math.max(0, last.end_time) : 0)
      const end = options?.endTime ?? (start + 5)
      const title = options?.title ?? '手动片段'

      tl.clips.push({
        id: newId,
        timeline_id: timelineId,
        title,
        event_type: 'HIGHLIGHT',
        start_time: start,
        end_time: end,
        order_index: tl.clips.length,
        transition_type: 'cut',
        transition_duration: 0.5,
        is_ai_generated: false,
      })

      draft.selectedTimelineId = timelineId
      draft.selectedClipId = newId
    }))
  }, [])

  /** Ensure at least one non-source editable timeline exists. Returns its id. */
  const ensureManualTimeline = useCallback((): string => {
    const existing = state.timelines.find(
      t => !t.name.startsWith('Source:'),
    )
    if (existing) return existing.id

    const newId = `local_manual_${Date.now()}`
    setState(produce(draft => {
      draft.timelines.push({
        id: newId,
        job_id: draft.timelines[0]?.job_id || '',
        name: 'Manual',
        order_index: draft.timelines.length,
        is_active: true,
        clips: [],
      })
    }))
    return newId
  }, [state.timelines])

  const addTimeline = useCallback(() => {
    const newId = `local_${Date.now()}`
    setState(produce(draft => {
      draft.timelines.push({
        id: newId,
        job_id: draft.timelines[0]?.job_id || '',
        name: `Timeline ${draft.timelines.length + 1}`,
        order_index: draft.timelines.length,
        is_active: true,
        clips: [],
      })
    }))
  }, [])

  const deleteTimeline = useCallback((timelineId: string) => {
    setState(produce(draft => {
      draft.timelines = draft.timelines.filter(t => t.id !== timelineId)
      draft.timelines.forEach((t, i) => { t.order_index = i })
      if (draft.selectedTimelineId === timelineId) {
        draft.selectedTimelineId = null
        draft.selectedClipId = null
      }
    }))
  }, [])

  const renameTimeline = useCallback((timelineId: string, name: string) => {
    setState(produce(draft => {
      const tl = draft.timelines.find(t => t.id === timelineId)
      if (tl) tl.name = name
    }))
  }, [])

  const reorderClips = useCallback((timelineId: string, clips: Clip[]) => {
    setState(produce(draft => {
      const tl = draft.timelines.find(t => t.id === timelineId)
      if (!tl) return
      tl.clips = clips.map((c, i) => ({ ...c, order_index: i }))
    }))
  }, [])

  const toRebuildRequest = useCallback((): RebuildRequest => ({
    timelines: state.timelines
      .filter(tl => !tl.name.startsWith('Source:'))
      .map(tl => ({
      timeline_id: tl.id,
      name: tl.name,
      clips: tl.clips.map(c => ({
        id: c.id,
        title: c.title,
        event_type: c.event_type,
        event_id: c.event_id,
        start_time: c.start_time,
        end_time: c.end_time,
        transition_type: c.transition_type,
        transition_duration: c.transition_duration,
        is_ai_generated: c.is_ai_generated,
        notes: c.notes,
      })),
    })),
  }), [state.timelines])

  const selectedClip = state.selectedClipId
    ? state.timelines
        .find(t => t.id === state.selectedTimelineId)
        ?.clips.find(c => c.id === state.selectedClipId) ?? null
    : null
  const currentRebuildFingerprint = useMemo(
    () => buildRebuildFingerprint(state.timelines),
    [state.timelines],
  )
  const baseRebuildFingerprint = useMemo(
    () => buildRebuildFingerprint(initialTimelines),
    [initialTimelines],
  )
  const hasPendingRebuild = currentRebuildFingerprint !== baseRebuildFingerprint

  return {
    timelines: state.timelines,
    selectedClipId: state.selectedClipId,
    selectedTimelineId: state.selectedTimelineId,
    selectedClip,
    setTimelines,
    selectClip,
    updateClip,
    deleteClip,
    moveClip,
    addClip,
    addTimeline,
    deleteTimeline,
    renameTimeline,
    reorderClips,
    toRebuildRequest,
    hasPendingRebuild,
    ensureManualTimeline,
  }
}
