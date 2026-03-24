/**
 * EditorWorkspace — the main editing workspace container.
 * Manages monitors, multi-timeline, AI insights, and inspector panels.
 * Works in ALL job states: queued/processing shows inline progress + manual editing.
 * Supports multiple source videos with tabs and incremental import.
 */
import React, { useState, useCallback, useRef } from 'react'
import { Save, Download, RotateCcw, Loader2, AlertCircle, Plus, Film } from 'lucide-react'
import { MultiTimeline } from '@/components/timeline/MultiTimeline'
import { ClipInspector } from '@/components/timeline/ClipInspector'
import { AIInsightsPanel } from '@/components/panels/AIInsightsPanel'
import { VideoMonitor } from '@/components/monitor/VideoMonitor'
import { useTimelineEditor } from '@/hooks/useTimelineEditor'
import { useVideoPlayer } from '@/hooks/useVideoPlayer'
import { rebuildJob, getDownloadUrl, addSource } from '@/services/api'
import { formatSeconds } from '@/utils/time'
import type { JobDetail, SourceInfo } from '@/types'

interface EditorWorkspaceProps {
  job: JobDetail
  onRebuildStart: () => void
}

export function EditorWorkspace({ job, onRebuildStart }: EditorWorkspaceProps) {
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [outputGuardMessage, setOutputGuardMessage] = useState<string | null>(null)
  const [activeSourceIndex, setActiveSourceIndex] = useState(0)
  const [pendingSourceSeek, setPendingSourceSeek] = useState<number | null>(null)

  // Source management
  const [localSources, setLocalSources] = useState<SourceInfo[]>(job.sources)
  const [addingSource, setAddingSource] = useState(false)
  const [addSourceProgress, setAddSourceProgress] = useState(0)
  const addSourceInputRef = useRef<HTMLInputElement>(null)

  // Sync sources when job data refreshes (e.g. after polling)
  React.useEffect(() => {
    if (job.sources.length > 0) {
      setLocalSources(job.sources)
    }
  }, [job.sources])

  const sources = localSources.length > 0 ? localSources : (
    job.source_path ? [{ index: 0, name: job.source_filename || 'Source' }] : []
  )
  const hasMultipleSources = sources.length > 1

  const isProcessing = job.status === 'queued' || job.status === 'processing'
  const canRebuild = job.status === 'completed' || job.status === 'failed'
  const hasAIResults = job.timelines.length > 0 && job.events.length > 0

  const editor = useTimelineEditor(job.timelines)
  const sourcePlayer = useVideoPlayer()
  const outputPlayer = useVideoPlayer()

  const sourceTimelines = [...editor.timelines]
    .filter(t => t.name.startsWith('Source:'))
    .sort((a, b) => a.order_index - b.order_index)

  // Build source URL — support multi-source via index
  const sourceUrl = job.source_path
    ? (
        sources.length > 1 || sourceTimelines.length > 0
          ? `/api/jobs/${job.id}/source?source_index=${activeSourceIndex}`
          : `/api/jobs/${job.id}/source`
      )
    : undefined

  const outputUrl = job.status === 'completed'
    ? `${getDownloadUrl(job.id)}?v=${encodeURIComponent(job.updated_at || job.completed_at || '')}`
    : undefined
  const selectedTimeline = editor.selectedTimelineId
    ? editor.timelines.find(t => t.id === editor.selectedTimelineId) ?? null
    : null
  const isSourceTrackSelected = (selectedTimeline?.name || '').startsWith('Source:')

  // ── Add Source ──

  const handleAddSourceFile = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return

    setAddingSource(true)
    setAddSourceProgress(0)
    try {
      const updatedSources = await addSource(job.id, file, p => setAddSourceProgress(p))
      setLocalSources(updatedSources)
      // Auto-switch to the newly added source
      setActiveSourceIndex(updatedSources.length - 1)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to add source')
    } finally {
      setAddingSource(false)
      setAddSourceProgress(0)
    }
  }, [job.id])

  // ── Mark In/Out → Add Clip logic ──

  const handleAddClipFromMarks = useCallback(() => {
    if (sourcePlayer.markIn == null || sourcePlayer.markOut == null) return
    if (sourcePlayer.markOut <= sourcePlayer.markIn) return

    const timelineId = editor.ensureManualTimeline()
    const sourceLabel = hasMultipleSources ? `[${sources[activeSourceIndex]?.name || `Source ${activeSourceIndex + 1}`}] ` : ''
    const title = `${sourceLabel}${formatSeconds(sourcePlayer.markIn)}-${formatSeconds(sourcePlayer.markOut)}`
    editor.addClip(timelineId, {
      startTime: sourcePlayer.markIn,
      endTime: sourcePlayer.markOut,
      title,
    })
    sourcePlayer.clearMarks()
  }, [sourcePlayer.markIn, sourcePlayer.markOut, sourcePlayer.clearMarks, editor, activeSourceIndex, sources, hasMultipleSources])

  // ── Source switching ──

  const handleSwitchSource = useCallback((idx: number) => {
    if (idx === activeSourceIndex) return
    setActiveSourceIndex(idx)
    sourcePlayer.clearMarks()
  }, [activeSourceIndex, sourcePlayer.clearMarks])

  // ── Source seeking ──

  const handleSeekSource = useCallback((timelineId: string, time: number) => {
    const sourceIdx = sourceTimelines.findIndex(t => t.id === timelineId)
    if (sourceIdx >= 0 && sourceIdx !== activeSourceIndex) {
      setActiveSourceIndex(sourceIdx)
      setPendingSourceSeek(time)
      return
    }
    sourcePlayer.seek(time)
  }, [activeSourceIndex, sourcePlayer.seek, sourceTimelines])

  React.useEffect(() => {
    if (sourceTimelines.length === 0) {
      if (activeSourceIndex !== 0 && sources.length <= 1) setActiveSourceIndex(0)
      return
    }
    if (activeSourceIndex < 0 || activeSourceIndex >= Math.max(sourceTimelines.length, sources.length)) {
      setActiveSourceIndex(0)
    }
  }, [activeSourceIndex, sourceTimelines.length, sources.length])

  React.useEffect(() => {
    if (pendingSourceSeek == null) return
    const video = sourcePlayer.elementRef.current
    if (!video) return

    const applySeek = () => {
      const target = Number.isFinite(video.duration)
        ? Math.max(0, Math.min(pendingSourceSeek, video.duration || pendingSourceSeek))
        : pendingSourceSeek
      sourcePlayer.seek(target)
      setPendingSourceSeek(null)
    }

    if (video.readyState >= 1) {
      applySeek()
      return
    }

    video.addEventListener('loadedmetadata', applySeek, { once: true })
    return () => video.removeEventListener('loadedmetadata', applySeek)
  }, [pendingSourceSeek, sourceUrl, sourcePlayer.seek, sourcePlayer.elementRef])

  // ── Output guard ──

  React.useEffect(() => {
    if (!outputGuardMessage) return
    const timer = window.setTimeout(() => setOutputGuardMessage(null), 3000)
    return () => window.clearTimeout(timer)
  }, [outputGuardMessage])

  const notifyOutputNeedsRebuild = useCallback(() => {
    setOutputGuardMessage('时间轴有未重建修改，请先点击 Save & Rebuild 生成最新输出视频。')
  }, [])

  // ── Playhead: always follows output only. No output → stays at 0. ──

  const playheadTime = outputPlayer.currentTime

  const handleRulerSeek = useCallback((seconds: number) => {
    // Ruler always controls the output player
    if (!outputUrl) return
    if (editor.hasPendingRebuild) {
      notifyOutputNeedsRebuild()
      return
    }
    outputPlayer.seek(seconds)
  }, [outputUrl, editor.hasPendingRebuild, outputPlayer.seek, notifyOutputNeedsRebuild])

  const handleOutputTogglePlay = useCallback(() => {
    if (editor.hasPendingRebuild) {
      notifyOutputNeedsRebuild()
      return
    }
    outputPlayer.togglePlay()
  }, [editor.hasPendingRebuild, notifyOutputNeedsRebuild, outputPlayer.togglePlay])

  const handleOutputSeek = useCallback((time: number) => {
    if (editor.hasPendingRebuild) {
      notifyOutputNeedsRebuild()
      return
    }
    outputPlayer.seek(time)
  }, [editor.hasPendingRebuild, notifyOutputNeedsRebuild, outputPlayer.seek])

  // ── Save & Rebuild ──

  const handleSaveAndRebuild = useCallback(async () => {
    setSaving(true)
    setSaveError(null)
    try {
      const request = editor.toRebuildRequest()
      await rebuildJob(job.id, request)
      onRebuildStart()
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }, [editor, job.id, onRebuildStart])

  return (
    <div className="flex flex-col h-full gap-2">
      {/* Top toolbar */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800 rounded-md border border-gray-700">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-200 truncate max-w-xs">{job.name}</span>
          <span className="text-xs text-gray-500">·</span>
          <span className="text-xs text-gray-400">{sources.length} sources</span>
          <span className="text-xs text-gray-400">
            · {editor.timelines.reduce((n, t) => n + t.clips.length, 0)} clips
          </span>

          {/* Inline processing indicator */}
          {isProcessing && (
            <>
              <span className="text-xs text-gray-500">·</span>
              <div className="flex items-center gap-1.5">
                <Loader2 className="w-3 h-3 text-blue-400 animate-spin" />
                <span className="text-xs text-blue-400">{job.progress_message || 'AI Processing...'}</span>
                <div className="w-20 h-1 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full transition-all duration-500"
                    style={{ width: `${Math.round(job.progress * 100)}%` }}
                  />
                </div>
                <span className="text-[10px] text-gray-500">{Math.round(job.progress * 100)}%</span>
              </div>
            </>
          )}
        </div>

        <div className="flex items-center gap-2">
          {saveError && <span className="text-xs text-red-400">{saveError}</span>}
          {outputGuardMessage && <span className="text-xs text-amber-300">{outputGuardMessage}</span>}

          {canRebuild && (
            <button
              onClick={handleSaveAndRebuild}
              disabled={saving}
              className={`flex items-center gap-1.5 text-xs disabled:opacity-50 text-white px-3 py-1.5 rounded transition-colors ${
                editor.hasPendingRebuild
                  ? 'bg-amber-600 hover:bg-amber-500 ring-1 ring-amber-300/70'
                  : 'bg-green-700 hover:bg-green-600'
              }`}
            >
              {saving ? (
                <RotateCcw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Save className="w-3.5 h-3.5" />
              )}
              {saving ? 'Saving...' : editor.hasPendingRebuild ? 'Rebuild Required' : 'Save & Rebuild'}
            </button>
          )}

          {job.status === 'completed' && (
            <a
              href={getDownloadUrl(job.id)}
              download
              className="flex items-center gap-1.5 text-xs bg-blue-700 hover:bg-blue-600 text-white px-3 py-1.5 rounded transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              Download
            </a>
          )}
        </div>
      </div>

      {/* Failed state banner */}
      {job.status === 'failed' && job.error_message && (
        <div className="flex items-center gap-2 px-3 py-2 bg-red-950/30 border border-red-900/40 rounded-md">
          <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
          <span className="text-xs text-red-300">{job.error_message}</span>
        </div>
      )}

      {/* Main editing area */}
      <div className="flex flex-1 gap-2 min-h-0">
        {/* Left: AI Insights (show when AI results available) */}
        {hasAIResults && (
          <div className="w-56 flex-shrink-0 bg-gray-900 border border-gray-700 rounded-md overflow-hidden">
            <AIInsightsPanel job={job} />
          </div>
        )}

        {/* Center: Monitors + Timeline */}
        <div className="flex-1 flex flex-col gap-2 min-w-0">
          {/* Source tabs bar */}
          <div className="flex items-center gap-1 px-1">
            {sources.map((src, idx) => (
              <button
                key={idx}
                onClick={() => handleSwitchSource(idx)}
                className={`
                  flex items-center gap-1 px-2.5 py-1 rounded text-xs transition-colors truncate max-w-[160px]
                  ${idx === activeSourceIndex
                    ? 'bg-gray-700 text-white'
                    : 'bg-gray-800/50 text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                  }
                `}
                title={src.name}
              >
                <Film className="w-3 h-3 flex-shrink-0" />
                <span className="truncate">{src.name || `Source ${idx + 1}`}</span>
              </button>
            ))}

            {/* Add source button */}
            <button
              onClick={() => addSourceInputRef.current?.click()}
              disabled={addingSource}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-500 hover:text-green-400 hover:bg-gray-800 transition-colors disabled:opacity-50"
              title="Add another source video"
            >
              {addingSource ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Plus className="w-3 h-3" />
              )}
              <span>{addingSource ? `${Math.round(addSourceProgress * 100)}%` : 'Add Source'}</span>
            </button>

            <input
              ref={addSourceInputRef}
              type="file"
              accept="video/*"
              className="hidden"
              onChange={handleAddSourceFile}
            />
          </div>

          {/* Monitors */}
          <div className={hasAIResults ? 'grid grid-cols-2 gap-2' : ''}>
            <VideoMonitor
              title={hasMultipleSources ? `Source: ${sources[activeSourceIndex]?.name || ''}` : 'Source'}
              videoRef={sourcePlayer.videoRef}
              src={sourceUrl}
              currentTime={sourcePlayer.currentTime}
              duration={sourcePlayer.duration}
              playing={sourcePlayer.playing}
              onTogglePlay={sourcePlayer.togglePlay}
              onSeek={sourcePlayer.seek}
              markIn={sourcePlayer.markIn}
              markOut={sourcePlayer.markOut}
              onMarkIn={sourcePlayer.handleMarkIn}
              onMarkOut={sourcePlayer.handleMarkOut}
              onClearMarks={sourcePlayer.clearMarks}
              onAddClipFromMarks={handleAddClipFromMarks}
            />
            {hasAIResults && (
              <VideoMonitor
                title="Output Preview"
                videoRef={outputPlayer.videoRef}
                src={outputUrl}
                currentTime={outputPlayer.currentTime}
                duration={outputPlayer.duration}
                playing={outputPlayer.playing}
                onTogglePlay={handleOutputTogglePlay}
                onSeek={handleOutputSeek}
                className={editor.hasPendingRebuild ? 'ring-1 ring-amber-400/70' : ''}
              />
            )}
          </div>

          {/* Multi-timeline */}
          <div className="flex-1 min-h-0" style={{ minHeight: '180px' }}>
            <MultiTimeline
              timelines={editor.timelines}
              selectedClipId={editor.selectedClipId}
              selectedTimelineId={editor.selectedTimelineId}
              onSelectClip={editor.selectClip}
              onMoveClip={editor.moveClip}
              onDeleteClip={editor.deleteClip}
              onAddClip={editor.addClip}
              onAddTimeline={editor.addTimeline}
              onDeleteTimeline={editor.deleteTimeline}
              onRenameTimeline={editor.renameTimeline}
              onSeekSource={handleSeekSource}
              onRulerSeek={handleRulerSeek}
              playheadSeconds={playheadTime}
            />
          </div>
        </div>

        {/* Right: Clip Inspector */}
        <div className="w-48 flex-shrink-0 bg-gray-900 border border-gray-700 rounded-md overflow-y-auto">
          <ClipInspector
            clip={editor.selectedClip}
            timelineId={editor.selectedTimelineId}
            onUpdate={editor.updateClip}
            onDelete={editor.deleteClip}
            readOnly={isSourceTrackSelected}
          />
        </div>
      </div>
    </div>
  )
}
