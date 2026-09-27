import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

async function component(name, dependencies = {}) {
  const source = await readFile(new URL(`../src/components/${name}.tsx`, import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText
  const exports = {}
  const require = createRequire(import.meta.url)
  runInNewContext(compiled, {
    exports,
    require: (id) => dependencies[id] ?? (id.startsWith('../lib/') ? {} : require(id)),
  })
  return exports[name]
}

const SpeechRecorder = await component('SpeechRecorder')
const CandidatePanel = await component('CandidatePanel', { './SpeechRecorder': { SpeechRecorder } })
const PrivacyPanel = await component('PrivacyPanel')
const StatusBar = await component('StatusBar')
const props = {
  socket: null, fsm: 'CANDIDATE_WAIT', detail: '', round: 'candidate', selectedIdx: null,
  spoken: null, grounding: [], fallback: true, labels: ['call Elena', '', '', '', 'Cancel'],
}

test('fallback preserves the selected intent, disables unused targets and marks the reply', () => {
  const html = renderToStaticMarkup(createElement(CandidatePanel, props))
  assert.match(html, /Fallback reply: your selected intent, unchanged/)
  assert.match(html, /call Elena/)
  const unused = (html.match(/<button\b[^>]*>[\s\S]*?<\/button>/g) ?? []).filter((button) => button.includes('Unused'))
  assert.equal(unused.length, 3)
  assert.ok(unused.every((button) => button.includes('disabled=""')))
  assert.match(html, /Cancel/)
  assert.doesNotMatch(html, /GROUNDED IN/)
})

test('manual recording is available only while the conversation is idle', () => {
  const ready = renderToStaticMarkup(createElement(SpeechRecorder, { ready: true, onBusy: () => {} }))
  assert.match(ready, /Record partner/)
  assert.doesNotMatch(ready, /disabled=""/)
  const busy = renderToStaticMarkup(createElement(SpeechRecorder, { ready: false, onBusy: () => {} }))
  assert.match(busy, /disabled=""/)
})

test('intent fallbacks are explicit and generated replies have no fallback notice', () => {
  const intent = renderToStaticMarkup(createElement(CandidatePanel, { ...props, round: 'intent' }))
  assert.match(intent, /Fallback choices: generation is unavailable/)
  const generated = renderToStaticMarkup(createElement(CandidatePanel, { ...props, fallback: false }))
  assert.doesNotMatch(generated, /Fallback reply|Fallback choices/)
})

test('privacy retains its ledger and purge control without an offline switch', () => {
  const html = renderToStaticMarkup(createElement(PrivacyPanel, { flows: [], cost: null }))
  assert.match(html, /No outbound activity recorded/)
  assert.match(html, /Purge stored data/)
  assert.doesNotMatch(html, /Local Mode|LOCAL MODE|Nothing has left|role="switch"/)
  const status = renderToStaticMarkup(createElement(StatusBar, {
    conn: { state: 'live' }, status: { providers: {}, input_badge: 'KEYBOARD' },
  }))
  assert.doesNotMatch(status, /LOCAL MODE/)
})
