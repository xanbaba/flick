import type { ClientMessage, WsMessage, WsType } from './types'
import { HIGH_RATE } from './types'

export type ConnState = { state: 'connecting' | 'live' | 'reconnecting'; retryMs: number }

export class FlickSocket {
  private ws: WebSocket | null = null
  private attempt = 0
  private everOpen = false
  private closed = false
  private timer: ReturnType<typeof setTimeout> | null = null

  constructor(
    private readonly url: string,
    private readonly onMessage: (msg: WsMessage) => void,
    private readonly onHighRate: (msg: WsMessage) => void,
    private readonly onConn: (state: ConnState) => void,
  ) {}

  start(): void {
    this.connect()
  }

  private connect(): void {
    if (this.closed) return
    this.onConn({ state: this.everOpen ? 'reconnecting' : 'connecting', retryMs: 0 })
    let ws: WebSocket
    try {
      ws = new WebSocket(this.url)
    } catch (err) {
      console.error('flick ws: bad url', this.url, err)
      this.scheduleRetry()
      return
    }
    this.ws = ws
    ws.onopen = () => {
      this.everOpen = true
      this.attempt = 0
      this.onConn({ state: 'live', retryMs: 0 })
      this.send({ type: 'client.request_snapshot', ts: Date.now() / 1000 })
    }
    ws.onmessage = (event) => {
      let msg: WsMessage
      try {
        msg = JSON.parse(String(event.data)) as WsMessage
      } catch (err) {
        console.warn('flick ws: non-JSON frame dropped', err)
        return
      }
      if (!msg || typeof msg.type !== 'string') {
        console.warn('flick ws: frame without type dropped', msg)
        return
      }
      if (HIGH_RATE.has(msg.type as WsType)) this.onHighRate(msg)
      else this.onMessage(msg)
    }
    ws.onclose = () => {
      this.ws = null
      if (!this.closed) this.scheduleRetry()
    }
  }

  private scheduleRetry(): void {
    const delay = Math.min(4000, 250 * 2 ** this.attempt++)
    this.onConn({ state: 'reconnecting', retryMs: delay })
    this.timer = setTimeout(() => this.connect(), delay)
  }

  send(msg: ClientMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg))
  }

  close(): void {
    this.closed = true
    if (this.timer) clearTimeout(this.timer)
    this.ws?.close()
  }
}

export function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
}
