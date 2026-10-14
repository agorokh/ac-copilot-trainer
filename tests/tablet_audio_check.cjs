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
  registerProcessor: (name, cls) => context.Processor = cls, currentFrame: 0});
vm.runInContext(fs.readFileSync(path.join(dir, "tablet_audio.js"), "utf8"), context);
vm.runInContext(fs.readFileSync(path.join(dir, "mic_worklet.js"), "utf8"), context);
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
  for (let i = 0; i < 16; i++) {
    context.currentFrame = i * 128;
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
