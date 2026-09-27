// Synthetic EEG + DSP for the in-browser mock. A JS port of scripts/fake_sensor.py's generator
// (pink noise, alpha, blinks, SSVEP ramped over 400 ms per ARCHITECTURE.md §8.4). Differences, all
// mock-only: no 60 Hz line noise is injected (it would be notched anyway), filtering is causal
// biquads, and PSD + rho use a fixed 2 s analysis buffer with a 3-harmonic FBCCA-weighted
// sinusoid projection. The numbers are computed from the synthetic waveform, never invented.

export const FS = 250, NCH = 8;
export const SIG = { pinkUv: 11, alphaHz: 10, alphaUv: 8, ssvepUv: 3, rampS: 0.4, blinkRate: 1 / 8, blinkS: 0.3, blinkUv: 80, harmonics: 3 };
const PINK_B = [0.049922035, -0.095993537, 0.050612699, -0.004408786];
const PINK_A = [1, -2.494956002, 2.017265875, -0.5221894];
const SSVEP_GAIN = [1, 1, 1, 1, 0.7, 0.7, 0.4, 0.4];
const BLINK_GAIN = [0.3, 0.3, 0.3, 0.5, 0.5, 0.5, 0.8, 0.8];

export const randn = () => { let u = 0; while (!u) u = Math.random(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * Math.random()); };
const expo = rate => -Math.log(1 - Math.random()) / rate;

export function coeffs(type, f0, q = Math.SQRT1_2) {
  const w = 2 * Math.PI * f0 / FS, c = Math.cos(w), al = Math.sin(w) / (2 * q), a0 = 1 + al;
  const b = type === 'hp' ? [(1 + c) / 2, -(1 + c), (1 + c) / 2] : type === 'lp' ? [(1 - c) / 2, 1 - c, (1 - c) / 2] : [1, -2 * c, 1];
  return [b[0] / a0, b[1] / a0, b[2] / a0, -2 * c / a0, (1 - al) / a0];
}
export class Biquad {
  constructor(k) { this.k = k; this.x1 = this.x2 = this.y1 = this.y2 = 0; }
  run(x) {
    const [b0, b1, b2, a1, a2] = this.k;
    const y = b0 * x + b1 * this.x1 + b2 * this.x2 - a1 * this.y1 - a2 * this.y2;
    this.x2 = this.x1; this.x1 = x; this.y2 = this.y1; this.y1 = y;
    return y;
  }
}
export function filtfilt(k, x) {
  let f = new Biquad(k);
  const y = Float64Array.from(x, v => f.run(v));
  f = new Biquad(k);
  for (let i = y.length - 1; i >= 0; i--) y[i] = f.run(y[i]);
  return y;
}

function fftPower(re) {
  const n = re.length, im = new Float64Array(n);
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { const t = re[i]; re[i] = re[j]; re[j] = t; }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = -2 * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang), half = len >> 1;
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < half; k++) {
        const a = i + k, b = a + half;
        const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
        const nc = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = nc;
      }
    }
  }
  const out = new Float64Array(n / 2 + 1);
  for (let k = 0; k <= n / 2; k++) out[k] = re[k] * re[k] + im[k] * im[k];
  return out;
}

export class Generator {
  constructor(bandpassLowHz) {
    this.t = 0;
    this.px = Array.from({ length: NCH }, () => [0, 0, 0]);
    this.py = Array.from({ length: NCH }, () => [0, 0, 0]);
    this.pv = 1e-3;
    this.walk = new Array(NCH).fill(0);
    this.nextBlink = expo(SIG.blinkRate);
    this.blinkPos = -1;
    this.setBandpass(bandpassLowHz);
    for (let i = 0; i < 6000; i++) this.pinkAll();
  }
  setBandpass(low) {
    this.hp = Array.from({ length: NCH }, () => [new Biquad(coeffs('hp', low)), new Biquad(coeffs('hp', low))]);
    this.lp = Array.from({ length: NCH }, () => new Biquad(coeffs('lp', 48)));
  }
  pinkAll() {
    const out = new Array(NCH);
    let s = 0;
    for (let ch = 0; ch < NCH; ch++) {
      const x = this.px[ch], y = this.py[ch], w = randn();
      const v = PINK_B[0] * w + PINK_B[1] * x[0] + PINK_B[2] * x[1] + PINK_B[3] * x[2] - PINK_A[1] * y[0] - PINK_A[2] * y[1] - PINK_A[3] * y[2];
      x[2] = x[1]; x[1] = x[0]; x[0] = w; y[2] = y[1]; y[1] = y[0]; y[0] = v;
      out[ch] = v; s += v * v;
    }
    this.pv = 0.9995 * this.pv + 0.0005 * (s / NCH);
    return out;
  }
  // ssvep: null | { freq, phase, age } — age in seconds since attention began
  generate(n, ssvep) {
    for (let ch = 0; ch < NCH; ch++) this.walk[ch] = Math.max(-0.5, Math.min(0.5, this.walk[ch] + randn() * 0.05));
    const data = Array.from({ length: NCH }, () => new Array(n));
    const scale = SIG.pinkUv / Math.sqrt(this.pv);
    const blinkLen = Math.round(SIG.blinkS * FS);
    for (let i = 0; i < n; i++) {
      const t = this.t / FS;
      const pk = this.pinkAll();
      const alpha = SIG.alphaUv * Math.sin(2 * Math.PI * SIG.alphaHz * t);
      let ss = 0;
      if (ssvep) {
        for (let h = 1; h <= SIG.harmonics; h++) ss += (1 / h) * Math.sin(2 * Math.PI * h * ssvep.freq * t + h * ssvep.phase);
        ss *= SIG.ssvepUv * Math.min(1, (ssvep.age + i / FS) / SIG.rampS);
      }
      if (this.blinkPos < 0 && t >= this.nextBlink) this.blinkPos = 0;
      let bl = 0;
      if (this.blinkPos >= 0) {
        bl = SIG.blinkUv * 0.5 * (1 - Math.cos(2 * Math.PI * this.blinkPos / (blinkLen - 1)));
        if (++this.blinkPos >= blinkLen) { this.blinkPos = -1; this.nextBlink = t + expo(SIG.blinkRate); }
      }
      for (let ch = 0; ch < NCH; ch++) {
        const raw = pk[ch] * scale + alpha * (1 + this.walk[ch]) + ss * SSVEP_GAIN[ch] + bl * BLINK_GAIN[ch];
        const [h1, h2] = this.hp[ch];
        data[ch][i] = this.lp[ch].run(h2.run(h1.run(raw)));
      }
      this.t++;
    }
    return data;
  }
}

// Welch-style single-segment PSD of the occipital mean, dB, 0.5 Hz grid 0..48 Hz.
export function psd(sig, fmax = 48) {
  const N = 512, n = Math.min(sig.length, N), x = new Float64Array(N);
  let m = 0;
  for (let i = 0; i < n; i++) m += sig[i];
  m /= n;
  let wss = 0;
  for (let i = 0; i < n; i++) { const w = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1)); x[i] = (sig[i] - m) * w; wss += w * w; }
  const P = fftPower(x), df = FS / N, freqs = [], power = [];
  for (let j = 0; j <= fmax * 2; j++) {
    const f = j / 2, k = f / df, k0 = Math.floor(k), fr = k - k0;
    const p = P[k0] * (1 - fr) + P[Math.min(k0 + 1, N / 2)] * fr;
    freqs.push(f);
    power.push(10 * Math.log10(2 * p / (FS * wss) + 1e-12));
  }
  return { freqs, power };
}

const NOTCH_ALPHA = coeffs('notch', SIG.alphaHz, 20);
const HW = [1, 2, 3].map(h => Math.pow(h, -1.25) + 0.25);
export function rhoScores(sig, freqs) {
  const n = sig.length, den = filtfilt(NOTCH_ALPHA, sig);
  return freqs.map(f => {
    const s0 = Math.abs(f - SIG.alphaHz) < 0.3 ? sig : den;
    let m = 0;
    for (let i = 0; i < n; i++) m += s0[i];
    m /= n;
    let ss = 0;
    for (let i = 0; i < n; i++) ss += (s0[i] - m) ** 2;
    let acc = 0, wsum = 0;
    for (let h = 1; h <= 3; h++) {
      if (h * f > 48) continue;
      let cs = 0, cc = 0;
      const w = 2 * Math.PI * h * f / FS;
      for (let i = 0; i < n; i++) { const v = s0[i] - m; cs += v * Math.sin(w * i); cc += v * Math.cos(w * i); }
      acc += HW[h - 1] * (cs * cs + cc * cc) / (ss * n / 2 + 1e-9);
      wsum += HW[h - 1];
    }
    return Math.min(1, Math.sqrt(acc / wsum));
  });
}

// Mirrors the §8.5 decision state machine's dwell counter (same rules as fake_sensor.DwellTracker).
export class DwellTracker {
  constructor({ rho_threshold, margin_ratio, dwell_windows }) { this.thr = rho_threshold; this.mr = margin_ratio; this.n = dwell_windows; this.winner = null; this.count = 0; }
  reset() { this.winner = null; this.count = 0; }
  update(rho) {
    const order = rho.map((v, i) => i).sort((a, b) => rho[b] - rho[a]);
    const w = order[0], second = rho[order[1]] ?? 0;
    const margin = rho[w] / (second + 1e-9);
    const above = rho[w] >= this.thr, ok = margin >= this.mr;
    if (above && ok && w === this.winner) this.count++;
    else if (above && ok) { this.winner = w; this.count = 1; }
    else { this.winner = null; this.count = 0; }
    const fired = this.count >= this.n;
    const count = this.count;
    if (fired) this.reset();
    return { winner_idx: w, margin, above_threshold: above, dwell_count: count, fired };
  }
}
