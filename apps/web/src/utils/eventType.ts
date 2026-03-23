import { EVENT_TYPE_LABELS } from '@/utils/constants'
import type { EventType } from '@/types'

const EVENT_TYPE_KEYS = new Set(Object.keys(EVENT_TYPE_LABELS))

const LABEL_TO_EVENT_TYPE: Record<string, EventType> = Object.entries(EVENT_TYPE_LABELS).reduce(
  (acc, [eventType, label]) => {
    acc[label] = eventType as EventType
    return acc
  },
  {} as Record<string, EventType>,
)

export function normalizeEventType(raw?: string | null): EventType | undefined {
  if (!raw) return undefined
  const upper = raw.toUpperCase()
  if (EVENT_TYPE_KEYS.has(upper)) return upper as EventType
  return undefined
}

export function inferEventTypeFromTitle(title?: string | null): EventType | undefined {
  if (!title) return undefined
  const [head] = title.split('·')
  const key = head.trim()
  if (!key) return undefined
  return LABEL_TO_EVENT_TYPE[key]
}

export function resolveEventType(rawType?: string | null, title?: string | null): EventType | undefined {
  return normalizeEventType(rawType) ?? inferEventTypeFromTitle(title)
}
