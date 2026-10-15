"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {webcrypto, createHash} = require("node:crypto");
const dir = path.join(__dirname, "../tools/ai_sidecar/voice/web");
const chunks = [];
const context = vm.createContext({console, crypto: webcrypto, Uint8Array, ArrayBuffer, DataView,
  setTimeout, clearTimeout, btoa: s => Buffer.from(s, "binary").toString("base64"),
  AudioWorkletProcessor: class { constructor() { this.port = {postMessage: v => chunks.push(v)}; } },
  registerProcessor: (name, cls) => context.Processor = cls, currentFrame: 0, sampleRate: 48000});
vm.runInContext(fs.readFileSync(path.join(dir, "tablet_audio.js"), "utf8"), context);
vm.runInContext(fs.readFileSync(path.join(dir, "mic_worklet.js"), "utf8"), context);
const dash = fs.readFileSync(path.join(dir, "../../dash/web/tablet_dash.html"), "utf8");
const liveSpinner = dash.match(/  function liveDiscreteSpinner\(level, modes, setupRange\) \{[\s\S]*?\n  \}/)[0];
const stepsOf = dash.match(/  function stepsOf\(sp\) \{[\s\S]*?\n  \}/)[0];
const fin = dash.match(/  function fin\([^\n]+/)[0];
vm.runInContext(fin + "\n" + stepsOf + "\n" + liveSpinner + ";globalThis.liveSpinner=liveDiscreteSpinner", context);
// Real Porsche/CSP response: modes=11, but spinner OFF..11 exposes 12 positions.
const porscheRange = {value:8, min:0, max:11, step:1};
const liveTc = context.liveSpinner(3, 11, porscheRange);
assert.equal(liveTc.value, 3); // actual physics, never the saved/setup value 8
assert.equal(liveTc.max, 11);
assert.equal((liveTc.max-liveTc.min)/liveTc.step+1, 12);
assert.equal(context.liveSpinner(0, 11, porscheRange).value, 0);
assert.equal(context.liveSpinner(11, 11, porscheRange).value, 11);
assert.equal(context.liveSpinner(12, 11, porscheRange).value, null);
assert.equal(context.liveSpinner(undefined, 11, porscheRange).value, null);
assert.equal(context.liveSpinner(0, 0, porscheRange), null);
for (const modes of [undefined, 11, 12]) {
  assert.equal(context.liveSpinner(3, modes).range_known, false);
}
assert.equal(context.liveSpinner(3, 11, {...porscheRange,range_known:false}).range_known, false);
assert.equal(context.liveSpinner(3, 11, {min:1,max:5,step:2}).value, 3);
assert.equal(context.liveSpinner(2, 11, {min:1,max:5,step:2}).value, null);
(async function () {
  const calls = [];
  let wired = true;
  const bridge = {playSound: (...args) => calls.push(args), stopSound: () => {},
    writeFileBase64: (file, data) => { assert.match(file, /\/files\/ac-copilot-voice\/[a-f0-9]{64}\.wav$/); return true; },
    getInternalAppSpecificStoragePath: () => "/app/files", createFolder: () => {},
    isWiredHeadsetOn: () => wired};
  const player = new context.CopilotTabletAudio.NativePlayer(bridge);
  const raw = new Uint8Array([1, 2, 3, 4]).buffer;
  const sha = createHash("sha256").update(Buffer.from(raw)).digest("hex");
  await player.preload({clip_id: "critical", sha256: sha}, raw);
  player.play("critical");
  assert.equal(calls[0][0], "file:///app/files/ac-copilot-voice/" + sha + ".wav");
  assert.equal(calls[0][1], false);
  assert.equal(calls[0][2], 3);
  wired = false;
  assert.throws(() => player.play("critical"), /wired/);
  await assert.rejects(player.preload({clip_id: "bad", sha256: "0".repeat(64)}, raw), /mismatch/);
  wired = true;
  assert.throws(() => player.play("bad"), /verified/);

  const processor = new context.Processor();
  assert.equal(processor.process([[]]), true); // source warm-up emits no fake samples
  assert.equal(chunks.length, 0);
  assert.equal(processor.process([[new Float32Array(128)]]), true);
  for (let i = 0; i < 16; i++) {
    context.currentFrame = 11648 + i * 128; // P7 initial capture-clock settlement
    const data = new Float32Array(128); data[0] = -1; data[1] = 1;
    assert.equal(processor.process([[data]]), true);
  }
  assert.equal(chunks.length, 1);
  assert.equal(chunks[0].byteLength, 4096);
  const view = new DataView(chunks[0]);
  assert.equal(view.getInt16(0, true), -32768);
  assert.equal(view.getInt16(2, true), 32767);
  context.currentFrame += 256; // a missing render block is a failure, never silence padding
  assert.equal(processor.process([[new Float32Array(128)]]), false);
  assert.match(chunks.at(-1).error, /gap/);
  assert.equal(processor.process([[new Float32Array(128)]]), false);
  console.log("native SHA/local path/wired gate and PCM16 worklet gap checks passed");
})().catch(err => { console.error(err); process.exitCode = 1; });
