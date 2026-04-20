/**
 * SocketIO singleton + task event stream subscription.
 * Follows unified-progress envelope schema.
 */

import { io, Socket } from "socket.io-client"

let socketInstance: Socket | null = null

export interface TaskEventEnvelope<P = unknown> {
  task_id: string
  user_id: number
  seq: number
  event: string
  payload: P
  emitted_at: string
}

export function getSocket(): Socket {
  if (!socketInstance) {
    socketInstance = io({ transports: ["websocket", "polling"] })
  }
  return socketInstance
}

export interface StreamOptions {
  taskIds: string[]
  onEvent: (env: TaskEventEnvelope) => void
  onStatusChange?: (s: "connecting" | "streaming" | "disconnected") => void
}

export function subscribeTaskStream(opts: StreamOptions) {
  const s = getSocket()
  const taskIds = new Set(opts.taskIds)
  const lastSeq = new Map<string, number>()

  const applyEnvelope = (env: TaskEventEnvelope) => {
    if (!env.task_id || !taskIds.has(env.task_id)) return
    const last = lastSeq.get(env.task_id) ?? 0
    if (env.seq <= last) return
    lastSeq.set(env.task_id, env.seq)
    opts.onEvent(env)
  }

  const onConnect = async () => {
    opts.onStatusChange?.("streaming")
    for (const tid of taskIds) {
      const since = lastSeq.get(tid) ?? 0
      try {
        const events: TaskEventEnvelope[] = await fetch(
          `/api/tasks/events?task_id=${tid}&since=${since}`
        ).then(r => r.json())
        events.forEach(applyEnvelope)
      } catch { /* skip */ }
    }
  }

  s.on("connect", onConnect)
  s.on("disconnect", () => opts.onStatusChange?.("disconnected"))
  s.onAny((_event: string, env: TaskEventEnvelope) => {
    if (env && typeof env === "object" && "task_id" in env) {
      applyEnvelope({ ...env, event: _event })
    }
  })

  if (s.connected) onConnect()
  else opts.onStatusChange?.("connecting")

  return {
    subscribe:   (id: string) => { taskIds.add(id); onConnect() },
    unsubscribe: (id: string) => { taskIds.delete(id); lastSeq.delete(id) },
    destroy:     () => { s.off("connect", onConnect) },
  }
}
