/**
 * VideoMonitor — displays a video player for source or output video.
 * Source monitor supports Mark In / Mark Out for manual clipping.
 */
import React from 'react'
import { Play, Pause, Volume2, Scissors, CornerDownLeft, CornerDownRight, X } from 'lucide-react'
import { formatSeconds } from '@/utils/time'
import type { Ref } from 'react'

interface VideoMonitorProps {
  title: string
  videoRef: Ref<HTMLVideoElement>
  src?: string
  currentTime: number
  duration: number
  playing: boolean
  onTogglePlay: () => void
  onSeek: (time: number) => void
  className?: string
  // Mark In/Out support (source monitor only)
  markIn?: number | null
  markOut?: number | null
  onMarkIn?: () => void
  onMarkOut?: () => void
  onClearMarks?: () => void
  onAddClipFromMarks?: () => void
}

export function VideoMonitor({
  title,
  videoRef,
  src,
  currentTime,
  duration,
  playing,
  onTogglePlay,
  onSeek,
  className = '',
  markIn,
  markOut,
  onMarkIn,
  onMarkOut,
  onClearMarks,
  onAddClipFromMarks,
}: VideoMonitorProps) {
  const progressPct = duration > 0 ? (currentTime / duration) * 100 : 0
  const hasMarkControls = !!(onMarkIn && onMarkOut)
  const canAddClip = markIn !== null && markIn !== undefined
    && markOut !== null && markOut !== undefined
    && markOut > markIn

  // Range highlight on progress bar
  const rangeLeftPct = duration > 0 && markIn != null ? (markIn / duration) * 100 : 0
  const rangeWidthPct = duration > 0 && markIn != null && markOut != null
    ? ((markOut - markIn) / duration) * 100
    : 0

  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!duration) return
    const rect = e.currentTarget.getBoundingClientRect()
    const pct = (e.clientX - rect.left) / rect.width
    onSeek(pct * duration)
  }

  return (
    <div className={`flex flex-col bg-gray-900 rounded-md overflow-hidden ${className}`}>
      {/* Monitor label */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800 border-b border-gray-700">
        <span className="text-xs font-medium text-gray-300 uppercase tracking-wider">{title}</span>
        <span className="text-xs text-gray-400">
          {formatSeconds(currentTime)} / {formatSeconds(duration)}
        </span>
      </div>

      {/* Video area */}
      <div className="relative flex-1 bg-black flex items-center justify-center min-h-[180px]">
        {src ? (
          <video
            ref={videoRef}
            src={src}
            className="max-w-full max-h-full"
            style={{ maxHeight: '240px' }}
            onClick={onTogglePlay}
          />
        ) : (
          <div className="text-gray-600 text-sm flex flex-col items-center gap-2">
            <div className="w-12 h-12 rounded-full border-2 border-gray-700 flex items-center justify-center">
              <Play className="w-5 h-5 text-gray-600 ml-1" />
            </div>
            <span>No video loaded</span>
          </div>
        )}

        {/* Play overlay */}
        {src && (
          <button
            className="absolute inset-0 flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity"
            onClick={onTogglePlay}
          >
            <div className="bg-black/50 rounded-full p-3">
              {playing ? (
                <Pause className="w-6 h-6 text-white" />
              ) : (
                <Play className="w-6 h-6 text-white ml-0.5" />
              )}
            </div>
          </button>
        )}
      </div>

      {/* Controls */}
      <div className="px-3 py-2 bg-gray-800 space-y-1.5">
        {/* Progress bar with mark range */}
        <div
          className="w-full h-1.5 bg-gray-700 rounded-full cursor-pointer relative"
          onClick={handleProgressClick}
        >
          {/* Selected range highlight */}
          {rangeWidthPct > 0 && (
            <div
              className="absolute top-0 h-full bg-green-500/30 rounded-full pointer-events-none"
              style={{ left: `${rangeLeftPct}%`, width: `${rangeWidthPct}%` }}
            />
          )}
          {/* Mark In indicator */}
          {markIn != null && duration > 0 && (
            <div
              className="absolute top-0 h-full w-0.5 bg-green-400 pointer-events-none z-10"
              style={{ left: `${(markIn / duration) * 100}%` }}
            />
          )}
          {/* Mark Out indicator */}
          {markOut != null && duration > 0 && (
            <div
              className="absolute top-0 h-full w-0.5 bg-red-400 pointer-events-none z-10"
              style={{ left: `${(markOut / duration) * 100}%` }}
            />
          )}
          {/* Playhead */}
          <div
            className="absolute left-0 top-0 h-full bg-blue-500 rounded-full transition-all pointer-events-none"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        {/* Buttons row */}
        <div className="flex items-center gap-2">
          <button
            onClick={onTogglePlay}
            disabled={!src}
            className="text-gray-300 hover:text-white disabled:opacity-40 transition-colors"
          >
            {playing ? (
              <Pause className="w-4 h-4" />
            ) : (
              <Play className="w-4 h-4" />
            )}
          </button>
          <Volume2 className="w-4 h-4 text-gray-500" />

          {/* Mark In/Out controls */}
          {hasMarkControls && src && (
            <>
              <div className="w-px h-4 bg-gray-700 mx-1" />

              <button
                onClick={onMarkIn}
                className="flex items-center gap-0.5 text-[10px] text-gray-400 hover:text-green-400 transition-colors"
                title="Mark In (set start point)"
              >
                <CornerDownRight className="w-3 h-3" />
                <span>I</span>
              </button>

              <button
                onClick={onMarkOut}
                className="flex items-center gap-0.5 text-[10px] text-gray-400 hover:text-red-400 transition-colors"
                title="Mark Out (set end point)"
              >
                <CornerDownLeft className="w-3 h-3" />
                <span>O</span>
              </button>

              {/* Mark info display */}
              {(markIn != null || markOut != null) && (
                <span className="text-[10px] text-gray-500 ml-1">
                  {markIn != null && <span className="text-green-400">{formatSeconds(markIn)}</span>}
                  {markIn != null && markOut != null && <span> - </span>}
                  {markOut != null && <span className="text-red-400">{formatSeconds(markOut)}</span>}
                </span>
              )}

              {(markIn != null || markOut != null) && (
                <button
                  onClick={onClearMarks}
                  className="text-gray-500 hover:text-gray-300 transition-colors"
                  title="Clear marks"
                >
                  <X className="w-3 h-3" />
                </button>
              )}

              {canAddClip && (
                <button
                  onClick={onAddClipFromMarks}
                  className="flex items-center gap-1 text-[10px] bg-green-700 hover:bg-green-600 text-white px-2 py-0.5 rounded transition-colors ml-1"
                  title="Add marked range as clip"
                >
                  <Scissors className="w-3 h-3" />
                  <span>Add Clip</span>
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
