/**
 * VideoMonitor — displays a video player for source or output video.
 */
import React from 'react'
import { Play, Pause, Volume2 } from 'lucide-react'
import { formatSeconds } from '@/utils/time'
import type { RefObject } from 'react'

interface VideoMonitorProps {
  title: string
  videoRef: RefObject<HTMLVideoElement>
  src?: string
  currentTime: number
  duration: number
  playing: boolean
  onTogglePlay: () => void
  onSeek: (time: number) => void
  className?: string
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
}: VideoMonitorProps) {
  const progressPct = duration > 0 ? (currentTime / duration) * 100 : 0

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
        {/* Progress bar */}
        <div
          className="w-full h-1.5 bg-gray-700 rounded-full cursor-pointer relative"
          onClick={handleProgressClick}
        >
          <div
            className="absolute left-0 top-0 h-full bg-blue-500 rounded-full transition-all"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        {/* Buttons */}
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
        </div>
      </div>
    </div>
  )
}
