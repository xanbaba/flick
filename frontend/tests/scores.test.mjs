import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const source = await readFile(new URL('../src/components/TargetScores.tsx', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText
const exports = {}
runInNewContext(compiled, { exports, require: createRequire(import.meta.url) })

test('score display follows configuration and the physical target count', () => {
  const html = renderToStaticMarkup(createElement(exports.TargetScores, {
    streams: { current: {} }, labels: [], frequencies: [], cancelIdx: 3,
    decision: { rho_threshold: 0.61, dwell_windows: 7, margin_ratio: 1.3 },
  }))
  assert.match(html, /threshold 0.61/)
  assert.equal((html.match(/data-row=/g) ?? []).length, 4)
  assert.equal((html.match(/data-pip=/g) ?? []).length, 28)
  assert.doesNotMatch(html, /0\.00|Hz/)
})

test('missing configuration does not display invented thresholds', () => {
  const html = renderToStaticMarkup(createElement(exports.TargetScores, {
    streams: { current: {} }, labels: [], frequencies: [], cancelIdx: -1,
  }))
  assert.doesNotMatch(html, /0\.35|data-row=|data-pip=/)
})
