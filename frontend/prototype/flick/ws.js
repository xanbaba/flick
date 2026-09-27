// Dashboard WebSocket client (ARCHITECTURE.md §16.3): one connection, exponential-backoff
// reconnect 250 ms → 4 s, a fresh graph.snapshot requested on every (re)connect. mode:
//   'backend' — real P3 only, retries forever
//   'auto'    — real P3; if the very first attempt never opens, fall back to the browser mock
//   'mock'    — browser mock only (flick/mock.js), which badges itself in sys.status

export class FlickSocket {
  constructor({ url, mode = 'mock', mockOptions = {}, onMessage, onConn }) {
    this.url = url;
    this.mode = mode;
    this.mockOptions = mockOptions;
    this.onMessage = onMessage;
    this.onConn = onConn;
    this.attempt = 0;
    this.everOpen = false;
    this.closed = false;
    this.mock = null;
    this.httpBase = url.replace(/^ws(s?):\/\//, 'http$1://').replace(/\/ws\/?$/, '');
  }

  start() { if (this.mode === 'mock') this.startMock(); else this.connect(); }

  async startMock() {
    const { MockServer } = await import('./mock.js');
    if (this.closed) return;
    this.mock = new MockServer(this.mockOptions);
    this.mock.onmessage = m => this.onMessage(m);
    this.mock.start();
    this.onConn({ state: 'mock' });
    this.send({ type: 'client.request_snapshot', ts: Date.now() / 1000 });
  }

  connect() {
    if (this.closed) return;
    this.onConn({ state: this.everOpen ? 'reconnecting' : 'connecting', retryMs: 0 });
    let ws;
    try { ws = new WebSocket(this.url); } catch (e) { console.error('flick ws: bad url', this.url, e); this.scheduleRetry(); return; }
    this.ws = ws;
    ws.onopen = () => {
      this.everOpen = true;
      this.attempt = 0;
      this.onConn({ state: 'live' });
      this.send({ type: 'client.request_snapshot', ts: Date.now() / 1000 });
    };
    ws.onmessage = e => {
      let msg;
      try { msg = JSON.parse(e.data); } catch (err) { console.warn('flick ws: non-JSON frame dropped', err); return; }
      if (msg && typeof msg.type === 'string') this.onMessage(msg);
      else console.warn('flick ws: frame without type dropped', msg);
    };
    ws.onclose = () => {
      this.ws = null;
      if (this.closed) return;
      if (!this.everOpen && this.mode === 'auto') { this.startMock(); return; }
      this.scheduleRetry();
    };
  }

  scheduleRetry() {
    const delay = Math.min(4000, 250 * 2 ** this.attempt++);
    this.onConn({ state: 'reconnecting', retryMs: delay });
    this.timer = setTimeout(() => this.connect(), delay);
  }

  send(msg) {
    if (this.mock) this.mock.receive(msg);
    else if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  async api(method, path, body) {
    if (this.mock) return this.mock.rest(method, path, body);
    const res = await fetch(this.httpBase + path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
    return res.json();
  }

  close() {
    this.closed = true;
    clearTimeout(this.timer);
    if (this.ws) this.ws.close();
    if (this.mock) this.mock.stop();
  }
}
