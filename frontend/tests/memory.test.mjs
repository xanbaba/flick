import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/memory.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText
const { MemoryState } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

const node = (id, weight = 1) => ({ id, label: id, kind: 'Thing', weight, last_accessed: 0 })
const edge = (id, source, target, weight = 1) => ({ id, source, target, kind: 'RELATES_TO', weight })

test('replayed blooms do not duplicate nodes or edges', () => {
  const memory = new MemoryState()
  const batch = { nodes: [node('a'), node('b')], edges: [edge('ab', 'a', 'b')] }
  memory.merge(batch)
  memory.merge(batch)
  assert.equal(memory.count, 2)
  assert.equal(memory.snapshot().edges.length, 1)
})

test('authoritative snapshots remove obsolete graph data and update weights', () => {
  const memory = new MemoryState()
  memory.merge({ nodes: [node('a'), node('b'), node('old')], edges: [edge('old-edge', 'a', 'old')] })
  const current = { nodes: [node('a', 2), node('b')], edges: [edge('ab', 'a', 'b', 1.15)] }
  memory.replace(current)
  assert.deepEqual(memory.snapshot(), current)
  assert.equal(memory.count, 2)
  memory.replace({ nodes: [], edges: [] })
  assert.deepEqual(memory.snapshot(), { nodes: [], edges: [] })
})

test('renderer remount receives all current blooms without replaying obsolete batches', () => {
  const memory = new MemoryState()
  memory.merge({ nodes: [node('old')], edges: [] })
  memory.replace({ nodes: [node('user')], edges: [] })
  memory.merge({ nodes: [node('learned')], edges: [edge('new', 'user', 'learned')] })
  const remount = memory.snapshot()
  assert.deepEqual(remount.nodes.map((n) => n.id), ['user', 'learned'])
  remount.nodes[0].weight = 99
  assert.equal(memory.snapshot().nodes[0].weight, 1)
})

test('onboarding exposes retryable server errors to the form', async () => {
  const apiSource = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8')
  const compiledApi = ts.transpileModule(apiSource, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }).outputText
  const { api } = await import(`data:text/javascript;base64,${Buffer.from(compiledApi).toString('base64')}`)
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Biography unavailable. Please try again.' }), { status: 503 })
  try {
    await assert.rejects(api.seed('A custom biography', 'Alex'), /Biography unavailable\. Please try again\./)
  } finally {
    globalThis.fetch = originalFetch
  }
})
