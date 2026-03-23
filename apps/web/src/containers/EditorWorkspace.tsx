/**
 * EditorWorkspace — the main editing workspace container.
 * Manages monitors, multi-timeline, AI insights, and inspector panels.
 */
import React, { useState, useCallback } from 'react'
import { Save, Download, RotateCcw } from 'lucide-react'
import { MultiTimeline } from '@/components/timeline/MultiTimeline'
import { ClipInspector } from '@/components/timeline/ClipInspector'
import { AIInsightsPanel } from '@/components/panels/AIInsightsPanel'
import { VideoMonitor } from '@/components/monitor/VideoMonitor'
import { useTimelineEditor } from '@/hooks/useTimelineEditor'
import { useVideoPlayer } from '@/hooks/useVideoPlayer'
import { rebuildJob, getDownloadUrl } from '@/services/api'
import type { JobDetail } from '@/types'

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

  const editor = useTimelineEditor(job.timelines)
  const sourcePlayer = useVideoPlayer()
  const outputPlayer = useVideoPlayer()

  const sourceTimelines = [...editor.timelines]
    .filter(t => t.name.startsWith('Source:'))
    .sort((a, b) => a.order_index - b.order_index)

  const sourceUrl = job.source_path
    ? (
        sourceTimelines.length > 0
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
      if (activeSourceIndex !== 0) setActiveSourceIndex(0)
      return
    }
    if (activeSourceIndex < 0 || activeSourceIndex >= sourceTimelines.length) {
      setActiveSourceIndex(0)
    }
  }, [activeSourceIndex, sourceTimelines.length])

  React.useEffect(() => {
    if (pendingSourceSeek == null) return
    const video = sourcePlayer.videoRef.current
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
  }, [pendingSourceSeek, sourceUrl, sourcePlayer.seek, sourcePlayer.videoRef])

  React.useEffect(() => {
    if (!outputGuardMessage) return
    const timer = window.setTimeout(() => setOutputGuardMessage(null), 3000)
    return () => window.clearTimeout(timer)
  }, [outputGuardMessage])

  const notifyOutputNeedsRebuild = useCallback(() => {
    setOutputGuardMessage('时间轴有未重建修改，请先点击 Save & Rebuild 生成最新输出视频。')
  }, [])

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
          <span className="text-xs text-gray-400">{editor.timelines.length} tracks</span>
          <span className="text-xs text-gray-400">
            · {editor.timelines.reduce((n, t) => n + t.clips.length, 0)} clips
          </span>
        </div>

        <div className="flex items-center gap-2">
          {saveError && <span className="text-xs text-red-400">{saveError}</span>}
          {outputGuardMessage && <span className="text-xs text-amber-300">{outputGuardMessage}</span>}
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

      {/* Main editing area */}
      <div className="flex flex-1 gap-2 min-h-0">
        {/* Left: AI Insights (narrow) */}
        <div className="w-56 flex-shrink-0 bg-gray-900 border border-gray-700 rounded-md overflow-hidden">
          <AIInsightsPanel job={job} />
        </div>

        {/* Center: Monitors + Timeline */}
        <div className="flex-1 flex flex-col gap-2 min-w-0">
          {/* Dual monitors */}
          <div className="grid grid-cols-2 gap-2">
            <VideoMonitor
              title="Source"
              videoRef={sourcePlayer.videoRef}
              src={sourceUrl}
              currentTime={sourcePlayer.currentTime}
              duration={sourcePlayer.duration}
              playing={sourcePlayer.playing}
              onTogglePlay={sourcePlayer.togglePlay}
              onSeek={sourcePlayer.seek}
            />
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
              playheadSeconds={outputPlayer.currentTime}
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
