import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/playback.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText

function harness() {
  let player
  let utterance
  let cancelled = 0
  class Audio {
    src = ''
    paused = true
    muted = false
    playCalls = 0
    pauseCalls = 0
    nextPlay = null
    constructor() { player = this }
    play() { this.playCalls++; this.paused = false; return this.nextPlay ?? Promise.resolve() }
    pause() { this.pauseCalls++; this.paused = true }
  }
  const exports = {}
  runInNewContext(compiled, {
    exports, Audio, atob, setTimeout, clearTimeout,
    console: { warn() {} },
    window: { speechSynthesis: {
      speak(value) { utterance = value },
      cancel() { cancelled++ },
    } },
    SpeechSynthesisUtterance: class { constructor(text) { this.text = text } },
  })
  return { api: exports, player, utterance: () => utterance, cancelled: () => cancelled }
}

test('cached WAV keeps its format and completes only on ended', async () => {
  const { api, player } = harness()
  const wav = Buffer.from('RIFFxxxxWAVEdata').toString('base64')
  let complete = false
  const playback = api.playAudio(wav, 'cache').then(() => { complete = true })
  await Promise.resolve()
  assert.equal(complete, false)
  assert.match(player.src, /^data:audio\/wav;base64,/)
  player.onended()
  await playback
  assert.equal(complete, true)
})

test('audio unlock does not interrupt an active reply', async () => {
  const { api, player } = harness()
  const playback = api.playAudio('SUQz', 'elevenlabs')
  api.unlockAudio()
  await Promise.resolve()
  assert.equal(player.playCalls, 1)
  assert.equal(player.pauseCalls, 0)
  assert.equal(player.muted, false)
  player.onended()
  await playback
})

test('an earlier unlock promise cannot pause a newer reply', async () => {
  const { api, player } = harness()
  let unlock
  player.nextPlay = new Promise((resolve) => { unlock = resolve })
  api.unlockAudio()
  player.nextPlay = null
  const playback = api.playAudio('SUQz', 'elevenlabs')
  unlock()
  await Promise.resolve()
  assert.equal(player.pauseCalls, 0)
  player.onended()
  await playback
})

test('browser speech completion follows the utterance end event', async () => {
  const { api, utterance } = harness()
  let complete = false
  const playback = api.speak('Hello').then(() => { complete = true })
  await Promise.resolve()
  assert.equal(complete, false)
  utterance().onend()
  await playback
  assert.equal(complete, true)
})

test('deadline stops browser speech and reports failure', async () => {
  const { api, cancelled } = harness()
  const outcome = await api.playReply({ text: 'Hello', voice: 'browser', playback_timeout_s: 0.01 })
  assert.equal(outcome, 'failed')
  assert.equal(cancelled(), 1)
})

test('disconnect cancellation stops audio before reporting failure', async () => {
  const { api, player } = harness()
  const playback = api.playReply({ text: 'Hello', voice: 'cache', audio_b64: 'SUQz' })
  api.stopPlayback()
  assert.equal(player.paused, true)
  assert.equal(await playback, 'failed')
})

test('blocked playback reports failure without claiming completion', async () => {
  const { api, player } = harness()
  player.nextPlay = Promise.reject(new Error('NotAllowedError'))
  const outcome = await api.playReply({ text: 'Hello', voice: 'cache', audio_b64: 'SUQz' })
  assert.equal(outcome, 'failed')
  assert.equal(player.paused, true)
})
