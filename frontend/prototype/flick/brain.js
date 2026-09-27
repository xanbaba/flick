// MemoryBrain (§16.2): wraps 3d-force-graph imperatively, outside React. The graph is created once;
// data changes go through graphData() mutation. Animations: pulse (graph.activate: particles along
// traversed edges + node swell, 600 ms), glow (grounding nodes: emissive for 3 s, then decay),
// bloom (graph.bloom: 0→full scale over 500 ms, sprouting from a neighbour, a particle drawing each edge).

import { hex } from './plots.js';

const THREE_V = '0.180.0';
const URLS = {
  three: `https://esm.sh/three@${THREE_V}`,
  fg: `https://esm.sh/3d-force-graph@^1.73.0?deps=three@${THREE_V}`,
  bloom: `https://esm.sh/three@${THREE_V}/examples/jsm/postprocessing/UnrealBloomPass.js`,
};
export const KIND_OKLCH = { Person: [0.80, 0.13, 25], Place: [0.78, 0.11, 250], Thing: [0.85, 0.12, 95], Activity: [0.76, 0.13, 305], Need: [0.80, 0.14, 60], Memory: [0.80, 0.10, 200] };
const KIND_HEX = Object.fromEntries(Object.entries(KIND_OKLCH).map(([k, v]) => [k, hex(...v)]));
const ACCENT_HEX = hex(0.87, 0.17, 158);
const easeOutBack = t => 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2;
const jitter = s => (Math.random() - 0.5) * s;
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export class MemoryBrain {
  static async create(el, opts = {}) {
    const [THREE, FG, B] = await Promise.all([import(URLS.three), import(URLS.fg), import(URLS.bloom).catch(e => { console.warn('MemoryBrain: bloom pass unavailable', e); return null; })]);
    return new MemoryBrain(el, THREE, FG.default, B && B.UnrealBloomPass, opts);
  }

  constructor(el, THREE, ForceGraph3D, UnrealBloomPass, opts) {
    this.T = THREE; this.el = el; this.opts = opts;
    this.nodes = new Map(); this.links = new Map(); this.fx = new Map();
    this.geo = new THREE.SphereGeometry(1, 20, 14);
    this.accent = new THREE.Color(ACCENT_HEX);
    const host = document.createElement('div');
    host.style.cssText = 'position:absolute;inset:0;';
    this.labelLayer = document.createElement('div');
    this.labelLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden;';
    el.append(host, this.labelLayer);
    this.labelPool = [];

    const g = new ForceGraph3D(host, { controlType: 'orbit' });
    g.width(el.clientWidth).height(el.clientHeight)
      .backgroundColor(opts.background || '#0b100e')
      .showNavInfo(false)
      .nodeThreeObject(n => this.makeNode(n))
      .nodeLabel(n => `<div style="font:500 12px 'Hanken Grotesk',sans-serif;padding:6px 9px;border-radius:6px;background:rgba(12,18,16,.92);border:1px solid rgba(255,255,255,.12);color:#e8f0ec"><span style="color:${KIND_HEX[n.kind] || '#ccc'};font:10px 'Martian Mono',monospace;letter-spacing:.06em;text-transform:uppercase">${esc(n.kind)}</span><br>${esc(n.label)}</div>`)
      .linkColor(() => 'rgba(185,225,205,1)')
      .linkOpacity(0.22)
      .linkWidth(0)
      .linkDirectionalParticles(0)
      .linkDirectionalParticleWidth(2.6)
      .linkDirectionalParticleSpeed(0.028)
      .linkDirectionalParticleColor(() => ACCENT_HEX)
      .d3AlphaDecay(0.018)
      .d3VelocityDecay(0.32)
      .cooldownTime(25000)
      .graphData({ nodes: [], links: [] });
    g.d3Force('charge').strength(-38);
    g.d3Force('link').distance(l => (l.kind === 'INVOLVES' ? 26 : 34));
    if (UnrealBloomPass) {
      const bp = new UnrealBloomPass(new THREE.Vector2(el.clientWidth, el.clientHeight), opts.bloomStrength ?? 1.4, 0.6, 0.16);
      g.postProcessingComposer().addPass(bp);
      this.bloomPass = bp;
    }
    const c = g.controls();
    if (c) { c.autoRotate = opts.autoRotate !== false; c.autoRotateSpeed = 0.5; c.addEventListener('start', () => { this.touched = performance.now(); }); }
    g.onEngineStop(() => this.fit(900));
    g.cameraPosition({ x: 0, y: 40, z: 300 });
    this.g = g;
    this.ro = new ResizeObserver(() => g.width(el.clientWidth).height(el.clientHeight));
    this.ro.observe(el);
    this.tick = this.tick.bind(this);
    this.raf = requestAnimationFrame(this.tick);
  }

  radius(w) { return 3 + 2.4 * Math.sqrt(Math.max(0.2, w || 1)); }

  makeNode(n) {
    const T = this.T, base = new T.Color(KIND_HEX[n.kind] || '#cccccc');
    const mat = new T.MeshLambertMaterial({ color: base, emissive: base.clone(), emissiveIntensity: 0.34, transparent: true, opacity: 0.95 });
    const m = new T.Mesh(this.geo, mat);
    n.__r = this.radius(n.weight); n.__m = m; n.__base = base;
    const f = this.fx.get(n.id);
    m.scale.setScalar(f && f.bloom != null ? 0.001 : n.__r);
    return m;
  }

  fxSet(id, key, t) { const f = this.fx.get(id) || {}; f[key] = t; this.fx.set(id, f); }

  tick() {
    const now = performance.now();
    for (const [id, f] of this.fx) {
      const n = this.nodes.get(id);
      if (!n || !n.__m) continue;
      let s = 1, glow = 0, live = false;
      if (f.bloom != null) {
        const t = (now - f.bloom) / 500;
        if (t < 1) { s = t <= 0 ? 0.001 : Math.max(0.001, easeOutBack(t)); glow = Math.max(glow, 0.8 * (1 - Math.max(0, t))); live = true; } else { f.bloom = null; f.born = now; }
      }
      if (f.pulse != null) {
        const t = (now - f.pulse) / 600;
        if (t < 0) live = true;
        else if (t < 1) { s *= 1 + 0.75 * Math.sin(Math.PI * t); glow = Math.max(glow, 1 - t); live = true; } else f.pulse = null;
      }
      if (f.glow != null) {
        const t = now - f.glow, e = t < 3000 ? 1 : Math.exp(-(t - 3000) / 500);
        if (e > 0.02) { glow = Math.max(glow, e); live = true; } else f.glow = null;
      }
      if (f.born != null) { if (now - f.born < 4000) live = true; else f.born = null; }
      n.__m.scale.setScalar(Math.max(0.001, n.__r * s));
      const mat = n.__m.material;
      if (glow > 0.01) { mat.emissive.copy(n.__base).lerp(this.accent, Math.min(1, glow)); mat.emissiveIntensity = 0.3 + 1.7 * glow; }
      else { mat.emissive.copy(n.__base); mat.emissiveIntensity = 0.34; }
      if (!live) this.fx.delete(id);
    }
    this.drawLabels(now);
    this.raf = requestAnimationFrame(this.tick);
  }

  drawLabels(now) {
    const picks = [];
    for (const [id, f] of this.fx) {
      const n = this.nodes.get(id);
      if (!n) continue;
      const pr = f.glow != null ? 3 : f.bloom != null || f.born != null ? 2 : f.pulse != null ? 1 : 0;
      if (pr) picks.push([pr, n]);
    }
    picks.sort((a, b) => b[0] - a[0]);
    const chosen = picks.slice(0, 12).map(p => ({ n: p[1], hot: true }));
    const have = new Set(chosen.map(c => c.n.id));
    for (const n of this.nodes.values()) if (n.kind === 'Person' && !have.has(n.id) && chosen.length < 18) chosen.push({ n, hot: false });
    const W = this.el.clientWidth, H = this.el.clientHeight, boxes = [];
    let used = 0;
    chosen.forEach(c => {
      const { n } = c;
      if (n.x == null) return;
      const p = this.g.graph2ScreenCoords(n.x, n.y, n.z);
      const x = p.x + (n.__r || 3) + 5, y = p.y - 9, w = n.label.length * 6.3 + 14;
      if (p.x < -50 || p.y < -20 || p.x > W + 50 || p.y > H + 20) return;
      if (boxes.some(b => x < b[0] + b[2] && x + w > b[0] && y < b[1] + 19 && y + 19 > b[1])) return;
      boxes.push([x, y, w]);
      let d = this.labelPool[used];
      if (!d) { d = document.createElement('div'); d.style.cssText = "position:absolute;left:0;top:0;white-space:nowrap;font:500 11px 'Hanken Grotesk',sans-serif;padding:2px 7px;border-radius:4px;"; this.labelLayer.appendChild(d); this.labelPool[used] = d; }
      used++;
      if (d.textContent !== n.label) d.textContent = n.label;
      d.style.display = 'block';
      d.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
      d.style.color = c.hot ? '#eafff4' : 'rgba(225,238,231,.72)';
      d.style.background = c.hot ? 'rgba(10,30,22,.8)' : 'transparent';
      d.style.boxShadow = c.hot ? `inset 0 0 0 1px ${ACCENT_HEX}66` : 'none';
    });
    for (let i = used; i < this.labelPool.length; i++) this.labelPool[i].style.display = 'none';
  }

  fit(ms) { if (!this.touched || performance.now() - this.touched > 10000) this.g.zoomToFit(ms, 30); }

  setSnapshot({ nodes = [], edges = [] }) {
    if (!nodes.length) { this.nodes.clear(); this.links.clear(); this.fx.clear(); this.g.graphData({ nodes: [], links: [] }); return; }
    if (!this.nodes.size) { this.bloom({ nodes, edges }, 5); return; }
    const keep = new Set(nodes.map(n => n.id));
    for (const id of [...this.nodes.keys()]) if (!keep.has(id)) this.nodes.delete(id);
    for (const [id, l] of [...this.links]) if (!this.nodes.has(l.source.id ?? l.source) || !this.nodes.has(l.target.id ?? l.target)) this.links.delete(id);
    const { nodes: curN } = this.g.graphData();
    this.g.graphData({ nodes: curN.filter(n => keep.has(n.id)), links: [...this.links.values()] });
    this.bloom({ nodes, edges }, 5, true);
  }

  bloom({ nodes = [], edges = [] }, stagger = 35, quiet = false) {
    const now = performance.now(), cur = this.g.graphData(), addN = [], addL = [];
    let i = 0;
    for (const raw of nodes) {
      const ex = this.nodes.get(raw.id);
      if (ex) {
        if (raw.weight !== ex.weight) { ex.weight = raw.weight; ex.__r = this.radius(raw.weight); }
        if (!quiet) this.fxSet(raw.id, 'pulse', now);
        continue;
      }
      const n = { ...raw };
      const e = edges.find(e => (e.source === n.id && this.nodes.has(e.target)) || (e.target === n.id && this.nodes.has(e.source)));
      const p = e && this.nodes.get(e.source === n.id ? e.target : e.source);
      if (p && p.x != null) { n.x = p.x + jitter(14); n.y = p.y + jitter(14); n.z = p.z + jitter(14); }
      this.nodes.set(n.id, n); addN.push(n);
      this.fxSet(n.id, 'bloom', now + i++ * stagger);
    }
    for (const raw of edges) {
      if (this.links.has(raw.id) || !this.nodes.has(raw.source) || !this.nodes.has(raw.target)) continue;
      const l = { ...raw };
      this.links.set(l.id, l); addL.push(l);
    }
    if (!addN.length && !addL.length) return;
    this.g.graphData({ nodes: [...cur.nodes, ...addN], links: [...cur.links, ...addL] });
    if (addL.length <= 40) setTimeout(() => addL.forEach(l => this.emit(l)), 80);
    clearTimeout(this.fitTimer);
    this.fitTimer = setTimeout(() => this.fit(1100), 900);
  }

  activate({ node_ids = [], edge_ids = [] }) {
    const now = performance.now(), set = new Set(node_ids);
    let ls = edge_ids.map(id => this.links.get(id)).filter(Boolean);
    if (!ls.length) ls = [...this.links.values()].filter(l => set.has(l.source.id ?? l.source) && set.has(l.target.id ?? l.target));
    ls.slice(0, 40).forEach((l, k) => setTimeout(() => this.emit(l), k * 25));
    node_ids.forEach((id, k) => this.fxSet(id, 'pulse', now + 120 + k * 60));
  }

  glow(ids = []) { const now = performance.now(); ids.forEach(id => this.nodes.has(id) && this.fxSet(id, 'glow', now)); }

  emit(link) {
    try { this.g.emitParticle(link); } catch (e) { console.warn('MemoryBrain: emitParticle failed', e); }
  }

  setAutoRotate(on) { const c = this.g.controls(); if (c) c.autoRotate = on; }
  setBloomStrength(s) { if (this.bloomPass) this.bloomPass.strength = s; }
  destroy() { cancelAnimationFrame(this.raf); this.ro.disconnect(); this.g._destructor(); }
}
