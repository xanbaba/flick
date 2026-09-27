import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/recording.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText

function harness(getUserMedia) {
  const exports = {}
  let stops = 0
  const stream = { getTracks: () => [{ stop: () => stops++ }] }
  class Recorder {
    static isTypeSupported(type) { return type.startsWith('audio/webm') }
    constructor(_stream, options) { this.mimeType = options.mimeType; this.state = 'inactive' }
    start() { this.state = 'recording' }
    stop() {
      this.state = 'inactive'
      this.ondataavailable({ data: new Blob(['encoded audio']) })
      this.onstop()
    }
  }
  runInNewContext(compiled, {
    exports, Blob, DOMException, MediaRecorder: Recorder,
    navigator: { mediaDevices: { getUserMedia: getUserMedia ?? (async () => stream) } },
  })
  return { start: exports.startRecording, stopped: () => stops, stream }
}

test('stop uploads one completed container and releases microphone first', async () => {
  const h = harness()
  const uploads = []
  const recording = await h.start(new AbortController().signal, (audio) => {
    assert.equal(h.stopped(), 1)
    uploads.push(audio)
  }, assert.fail)
  assert.equal(uploads.length, 0)
  recording.stop()
  recording.stop()
  assert.equal(uploads.length, 1)
  assert.equal(await uploads[0].text(), 'encoded audio')
  assert.equal(uploads[0].type, 'audio/webm;codecs=opus')
})

test('cancel discards audio rather than uploading on component exit', async () => {
  const h = harness()
  const controller = new AbortController()
  await h.start(controller.signal, () => assert.fail('cancel must not upload'), assert.fail)
  controller.abort()
  assert.ok(h.stopped() >= 1)
})

test('permission resolving after unmount releases the newly acquired microphone', async () => {
  let resolve
  const h = harness(() => new Promise((done) => { resolve = done }))
  const controller = new AbortController()
  const pending = h.start(controller.signal, assert.fail, assert.fail)
  controller.abort()
  resolve(h.stream)
  await assert.rejects(pending, { name: 'AbortError' })
  assert.equal(h.stopped(), 1)
})
