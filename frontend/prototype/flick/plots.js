// uPlot-backed EEG trace and PSD (§16.2), plus the spectrogram waterfall. Data arrives at 4 Hz
// through push(); frame() runs on the dashboard's requestAnimationFrame loop, never React state.

export function oklchToRgb(L, C, h) {
  const a = C * Math.cos(h * Math.PI / 180), b = C * Math.sin(h * Math.PI / 180);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const lin = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
  return lin.map(x => { x = Math.max(0, Math.min(1, x)); return Math.round(255 * (x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055)); });
}
export const hex = (L, C, h) => '#' + oklchToRgb(L, C, h).map(v => v.toString(16).padStart(2, '0')).join('');

let uPlotPromise = null;
export function loadUPlot() {
  if (!uPlotPromise) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://cdn.jsdelivr.net/npm/uplot@1.6.30/dist/uPlot.min.css';
    document.head.appendChild(link);
    uPlotPromise = import('https://esm.sh/uplot@1.6.30').then(m => m.default);
  }
  return uPlotPromise;
}

const FONT = '10px "Martian Mono", monospace';

export class EegTrace {
  constructor(uPlot, el, { channels, colors, grid, windowS = 4, spacing = 36 }) {
    this.el = el; this.n = channels.length; this.win = windowS; this.sp = spacing; this.grid = grid;
    this.fs = 250; this.total = 0; this.play = null; this.last = performance.now(); this.dirty = false;
    this.xs = []; this.ys = Array.from({ length: this.n }, () => []);
    this.min = -windowS; this.max = 0;
    const series = [{}, ...channels.map((c, k) => ({ stroke: colors[k], width: 1.1, points: { show: false } }))];
    this.u = new uPlot({
      width: Math.max(10, el.clientWidth), height: Math.max(10, el.clientHeight),
      pxAlign: 0, cursor: { show: false }, legend: { show: false }, select: { show: false },
      padding: [0, 0, 0, 0],
      scales: { x: { time: false, auto: false, range: () => [this.min, this.max] }, y: { auto: false, range: () => [-(this.n - 0.5) * this.sp, 0.5 * this.sp] } },
      axes: [{ show: false }, { show: false }],
      series,
      hooks: { drawClear: [u => this.drawGrid(u)] },
    }, [[], ...this.ys], el);
    this.ro = new ResizeObserver(() => this.u.setSize({ width: Math.max(10, el.clientWidth), height: Math.max(10, el.clientHeight) }));
    this.ro.observe(el);
  }
  push({ data, fs }) {
    this.fs = fs || 250;
    const n = data[0].length, cap = Math.round(this.fs * (this.win + 1.5)), lim = this.sp * 0.95;
    for (let i = 0; i < n; i++) this.xs.push((this.total + i) / this.fs);
    for (let k = 0; k < this.n; k++) {
      const col = data[k] || [], ys = this.ys[k];
      for (let i = 0; i < n; i++) ys.push(Math.max(-lim, Math.min(lim, col[i] || 0)) - k * this.sp);
    }
    this.total += n;
    if (this.xs.length > cap + 250) {
      const cut = this.xs.length - cap;
      this.xs.splice(0, cut);
      this.ys.forEach(y => y.splice(0, cut));
    }
    this.dirty = true;
  }
  frame(now) {
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    if (!this.total) return;
    const head = this.total / this.fs, target = head - 0.3;
    if (this.play == null || Math.abs(target - this.play) > 1.5) this.play = target;
    this.play += dt + (target - this.play) * 0.06;
    if (this.play > head) this.play = head;
    this.min = this.play - this.win; this.max = this.play;
    if (this.dirty) { this.u.setData([this.xs, ...this.ys], false); this.dirty = false; }
    this.u.setScale('x', { min: this.min, max: this.max });
  }
  drawGrid(u) {
    const { ctx, bbox } = u;
    ctx.save();
    ctx.strokeStyle = this.grid; ctx.lineWidth = 1;
    for (let s = Math.ceil(this.min); s <= this.max; s++) {
      const x = Math.round(u.valToPos(s, 'x', true)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, bbox.top); ctx.lineTo(x, bbox.top + bbox.height); ctx.stroke();
    }
    ctx.restore();
  }
  destroy() { this.ro.disconnect(); this.u.destroy(); }
}

export class PsdPlot {
  constructor(uPlot, el, wf, { accent, text, muted, grid, fill }) {
    this.el = el; this.wf = wf; this.c = { accent, text, muted, grid };
    this.freqs = null; this.disp = null; this.target = null; this.fresh = false;
    this.targets = []; this.cancelIdx = -1; this.winner = -1; this.hot = false;
    this.yLo = -15; this.yHi = 20; this.cLo = -10; this.cHi = 15;
    this.lut = buildLut();
    this.u = new uPlot({
      width: Math.max(10, el.clientWidth), height: Math.max(10, el.clientHeight),
      pxAlign: 0, cursor: { show: false }, legend: { show: false }, select: { show: false },
      padding: [14, 6, 0, 6],
      scales: { x: { time: false, auto: false, range: [0, 48] }, y: { auto: false, range: () => [this.yLo, this.yHi] } },
      axes: [
        { stroke: muted, font: FONT, size: 20, gap: 3, grid: { show: false }, ticks: { stroke: grid, size: 3 }, splits: () => [0, 6, 12, 18, 24, 30, 36, 42, 48], values: (u, v) => v.map(x => (x === 48 ? '48 Hz' : String(x))) },
        { show: false },
      ],
      series: [{}, { stroke: accent, width: 1.6, fill, fillTo: u => u.scales.y.min, points: { show: false } }],
      hooks: { drawClear: [u => this.under(u)], draw: [u => this.over(u)] },
    }, [[0, 48], [0, 0]], el);
    this.ro = new ResizeObserver(() => this.u.setSize({ width: Math.max(10, el.clientWidth), height: Math.max(10, el.clientHeight) }));
    this.ro.observe(el);
  }
  setTargets(freqs, cancelIdx) { this.targets = freqs || []; this.cancelIdx = cancelIdx ?? -1; }
  setWinner(idx, hot) { this.winner = idx; this.hot = hot; }
  push({ freqs, power }) {
    this.freqs = freqs; this.target = power;
    if (!this.disp || this.disp.length !== power.length) this.disp = power.slice();
    const band = power.filter((_, i) => freqs[i] >= 4);
    const lo = Math.min(...band), hi = Math.max(...band);
    this.yLo += (lo - 4 - this.yLo) * 0.15; this.yHi += (hi + 5 - this.yHi) * 0.15;
    this.cLo += (lo - this.cLo) * 0.1; this.cHi += (hi - this.cHi) * 0.1;
    this.fresh = true;
  }
  readout(winner, hot) {
    if (!this.target || !this.targets.length) return null;
    const band = this.target.filter((_, i) => this.freqs[i] >= 5 && this.freqs[i] <= 45).sort((a, b) => a - b);
    const median = band[Math.floor(band.length / 2)];
    const at = f => this.target[Math.round(f * 2)] - median;
    return hot && winner >= 0 ? { label: `${this.targets[winner].toFixed(1)} Hz`, snr: at(this.targets[winner]) } : { label: 'α 10 Hz', snr: at(10) };
  }
  frame() {
    if (!this.disp) return;
    for (let i = 0; i < this.disp.length; i++) this.disp[i] += (this.target[i] - this.disp[i]) * 0.3;
    this.u.batch(() => {
      this.u.setData([this.freqs, this.disp], false);
      this.u.setScale('x', { min: 0, max: 48 });
      this.u.setScale('y', { min: this.yLo, max: this.yHi });
    });
    if (this.fresh) { this.fresh = false; this.row(); }
  }
  under(u) {
    const { ctx, bbox } = u, x0 = u.valToPos(8, 'x', true), x1 = u.valToPos(12, 'x', true);
    ctx.save();
    ctx.fillStyle = 'rgba(255,255,255,0.035)';
    ctx.fillRect(x0, bbox.top, x1 - x0, bbox.height);
    ctx.fillStyle = this.c.muted; ctx.font = `${10 * devicePixelRatio}px "Martian Mono", monospace`; ctx.textAlign = 'center';
    ctx.fillText('α', (x0 + x1) / 2, bbox.top + bbox.height - 6 * devicePixelRatio);
    ctx.restore();
  }
  over(u) {
    const { ctx, bbox } = u, dpr = devicePixelRatio;
    ctx.save();
    ctx.font = `${10 * dpr}px "Martian Mono", monospace`; ctx.textAlign = 'center';
    this.targets.forEach((f, i) => {
      const x = Math.round(u.valToPos(f, 'x', true)) + 0.5, win = i === this.winner && this.hot;
      ctx.strokeStyle = win ? this.c.accent : this.c.grid;
      ctx.lineWidth = win ? 1.5 * dpr : dpr;
      ctx.setLineDash(win ? [] : [3 * dpr, 3 * dpr]);
      ctx.beginPath(); ctx.moveTo(x, bbox.top); ctx.lineTo(x, bbox.top + bbox.height); ctx.stroke();
      ctx.fillStyle = win ? this.c.accent : this.c.muted;
      ctx.fillText(i === this.cancelIdx ? '✕' : String(i + 1), x, bbox.top - 3 * dpr);
      if (win) {
        ctx.setLineDash([1.5 * dpr, 3 * dpr]); ctx.lineWidth = dpr; ctx.strokeStyle = this.c.accent;
        [2, 3].forEach(h => {
          if (f * h > 48) return;
          const xh = Math.round(u.valToPos(f * h, 'x', true)) + 0.5;
          ctx.beginPath(); ctx.moveTo(xh, bbox.top + 8 * dpr); ctx.lineTo(xh, bbox.top + bbox.height); ctx.stroke();
          ctx.fillText(`${h}f`, xh, bbox.top + 6 * dpr);
        });
      }
    });
    ctx.restore();
  }
  row() {
    const cv = this.wf; if (!cv || !this.freqs) return;
    const u = this.u, dpr = devicePixelRatio;
    const left = u.bbox.left / dpr, width = u.bbox.width / dpr;
    if (cv.style.left !== `${left}px`) { cv.style.left = `${left}px`; cv.style.width = `${width}px`; }
    const W = Math.max(8, Math.round(width * dpr)), H = Math.max(8, Math.round(cv.clientHeight * dpr));
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    const ctx = cv.getContext('2d'), rowH = Math.max(1, Math.round(dpr));
    ctx.drawImage(cv, 0, rowH);
    const img = ctx.createImageData(W, rowH), span = Math.max(1, this.cHi - this.cLo + 4);
    for (let x = 0; x < W; x++) {
      const k = (x / (W - 1)) * 96, k0 = Math.floor(k), fr = k - k0;
      const p = this.target[k0] * (1 - fr) + (this.target[Math.min(96, k0 + 1)] ?? this.target[k0]) * fr;
      const t = Math.max(0, Math.min(1, (p - this.cLo + 2) / span)) ** 1.6;
      const c = this.lut[Math.round(t * 255)];
      for (let y = 0; y < rowH; y++) { const o = (y * W + x) * 4; img.data[o] = c[0]; img.data[o + 1] = c[1]; img.data[o + 2] = c[2]; img.data[o + 3] = 255; }
    }
    ctx.putImageData(img, 0, 0);
  }
  destroy() { this.ro.disconnect(); this.u.destroy(); }
}

function buildLut() {
  const stops = [[0.16, 0.01, 160], [0.36, 0.08, 175], [0.62, 0.15, 160], [0.87, 0.17, 158], [0.98, 0.04, 120]];
  return Array.from({ length: 256 }, (_, i) => {
    const t = i / 255 * (stops.length - 1), j = Math.min(stops.length - 2, Math.floor(t)), f = t - j;
    const [a, b] = [stops[j], stops[j + 1]];
    return oklchToRgb(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f);
  });
}
