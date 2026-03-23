// Application constants

export const EVENT_TYPE_LABELS: Record<string, string> = {
  SOURCE: '原片片段',
  GOAL: '进球',
  SHOT_ON_TARGET: '射正',
  SHOT_BLOCKED: '射门被封堵',
  SAVE: '扑救',
  CORNER_KICK: '角球',
  FREE_KICK: '任意球',
  OFFSIDE: '越位',
  FOUL: '犯规',
  SUBSTITUTION: '换人',
  YELLOW_CARD: '黄牌',
  RED_CARD: '红牌',
  PENALTY: '点球',
  VAR: 'VAR回看',
  HIGHLIGHT: '精彩镜头',
}

export const EVENT_TYPE_COLORS: Record<string, string> = {
  SOURCE: '#64748b',     // slate
  GOAL: '#22c55e',       // green
  SHOT_ON_TARGET: '#3b82f6', // blue
  SHOT_BLOCKED: '#0ea5e9', // sky
  SAVE: '#6366f1',       // indigo
  CORNER_KICK: '#10b981', // emerald
  FREE_KICK: '#f59e0b', // amber
  OFFSIDE: '#f43f5e', // rose
  FOUL: '#ef4444', // red
  SUBSTITUTION: '#14b8a6', // teal
  YELLOW_CARD: '#eab308', // yellow
  RED_CARD: '#ef4444',   // red
  PENALTY: '#f97316',    // orange
  VAR: '#8b5cf6',        // purple
  HIGHLIGHT: '#06b6d4',  // cyan
}

export const TRANSITION_TYPE_LABELS: Record<string, string> = {
  cut: 'Hard Cut',
  fade: 'Fade',
  wipe: 'Wipe',
  slide: 'Slide',
  circle: 'Circle Open',
}

export const STATUS_COLORS: Record<string, string> = {
  queued: '#6b7280',
  processing: '#3b82f6',
  completed: '#22c55e',
  failed: '#ef4444',
  canceled: '#9ca3af',
}

export const STATUS_LABELS: Record<string, string> = {
  queued: 'Queued',
  processing: 'Processing',
  completed: 'Completed',
  failed: 'Failed',
  canceled: 'Canceled',
}

export const POLLING_INTERVAL_MS = 2000
export const TIMELINE_PX_PER_SECOND = 8
export const MIN_CLIP_DURATION = 1 // seconds
export const TIMELINE_SNAP_SECONDS = 0.5
