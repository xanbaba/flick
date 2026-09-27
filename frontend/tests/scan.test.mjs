import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/scan.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText
const exports = {}
runInNewContext(compiled, { exports })
const { reduceScan, scanKey } = exports

const msg = (type, payload) => ({ type, ts: 0, payload })
const targets = msg('scan.targets', {
  trial_id: 't1', labels: ['Yes', 'No', 'More', 'Cancel'], round: 'intent', cancel_idx: 3, highlight_idx: 0,
})

test('highlight follows scan messages for the current trial only', () => {
  let s = reduceScan(null, targets)
  assert.equal(s.highlightIdx, 0)
  s = reduceScan(s, msg('scan.highlight', { trial_id: 't1', highlight_idx: 2 }))
  assert.equal(s.highlightIdx, 2)
  s = reduceScan(s, msg('scan.highlight', { trial_id: 'old', highlight_idx: 1 }))
  assert.equal(s.highlightIdx, 2)
  s = reduceScan(s, msg('scan.selected', { trial_id: 't1', target_idx: 2, hold_s: 0.6 }))
  assert.equal(s.selectedIdx, 2)
  s = reduceScan(s, msg('scan.highlight', { trial_id: 't1', highlight_idx: 3 }))
  assert.equal(s.highlightIdx, 2, 'no movement after a selection')
  assert.equal(reduceScan(s, msg('scan.idle', { trial_id: 'other', reason: 'x' })), s)
  assert.equal(reduceScan(s, msg('scan.idle', { trial_id: 't1', reason: 'selected' })), null)
})

test('keys map to scan actions only while a scan is showing', () => {
  const s = reduceScan(null, targets)
  assert.equal(scanKey('n', s), 'n')
  assert.equal(scanKey('ArrowRight', s), 'n')
  assert.equal(scanKey('Enter', s), 's')
  assert.equal(scanKey('4', s), '4')
  assert.equal(scanKey('5', s), null)
  assert.equal(scanKey('n', null), null)
  assert.equal(scanKey('5', null), '5')
  assert.equal(scanKey('6', null), null)
})
