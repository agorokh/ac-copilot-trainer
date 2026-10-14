/* Existing tablet endpoint helpers: native local-bank probe and opt-in microphone (#531). */
"use strict";
(function (root) {
  function base64(bytes) {
    var text = "";
    for (var i = 0; i < bytes.length; i++) text += String.fromCharCode(bytes[i]);
    return btoa(text);
  }

  function NativePlayer(bridge) {
    this.bridge = bridge;
    this.files = Object.create(null);
    this.ready = !!(bridge && bridge.playSound && bridge.stopSound &&
      bridge.writeFileBase64 && bridge.getInternalAppSpecificStoragePath && bridge.isWiredHeadsetOn);
  }
  NativePlayer.prototype.preload = async function (entry, raw) {
    if (!this.ready) throw new Error("Fully JavaScript interface unavailable");
    if (!/^[a-f0-9]{64}$/.test(entry.sha256 || "")) throw new Error("clip SHA-256 missing");
    var digest = new Uint8Array(await crypto.subtle.digest("SHA-256", raw));
    var hex = Array.from(digest, function (x) { return x.toString(16).padStart(2, "0"); }).join("");
    if (hex !== entry.sha256) throw new Error("clip SHA-256 mismatch");
    var dir = this.bridge.getInternalAppSpecificStoragePath().replace(/\/$/, "") + "/ac-copilot-voice";
    this.bridge.createFolder(dir);
    var path = dir + "/" + hex + ".wav";
    if (!this.bridge.writeFileBase64(path, base64(new Uint8Array(raw)))) {
      throw new Error("native clip cache write failed");
    }
    this.files[entry.clip_id] = "file://" + path;
  };
  NativePlayer.prototype.wired = function () {
    return this.ready && this.bridge.isWiredHeadsetOn() === true;
  };
  NativePlayer.prototype.play = function (clipId) {
    if (!this.wired()) throw new Error("wired earpiece required; PC remains authoritative");
    var file = this.files[clipId];
    if (!file) throw new Error("native clip is not verified/cached");
    this.bridge.stopSound();
    this.bridge.playSound(file, false, 3);
    // A successful Java call is a dispatch request, never an acoustic onset.
  };
  NativePlayer.prototype.stop = function () {
    if (this.ready) this.bridge.stopSound();
  };

  function Microphone(getSocket, status) {
    this.getSocket = getSocket;
    this.status = status;
    this.stream = null;
    this.ctx = null;
    this.node = null;
    this.timer = null;
    this.starting = false;
    this.generation = 0;
    this.captureId = null;
  }
  Microphone.prototype.start = async function () {
    if (this.stream || this.starting) return;
    this.starting = true;
    var generation = ++this.generation;
    var self = this;
    try {
      if (!window.isSecureContext || !navigator.mediaDevices) throw new Error("microphone needs localhost/HTTPS");
      var ws = this.getSocket();
      if (!ws || ws.readyState !== 1) throw new Error("connect before recording");
      var stream = await navigator.mediaDevices.getUserMedia({audio: {
        channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false
      }, video: false});
      if (generation !== this.generation) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
      this.stream = stream;
      var settings = stream.getAudioTracks()[0].getSettings();
      // Requested constraints are not proof of the effective capture path.
      if (settings.echoCancellation !== false || settings.noiseSuppression !== false ||
          settings.autoGainControl !== false) throw new Error("raw microphone processing settings unverified");
      this.ctx = new AudioContext({latencyHint: "interactive"});
      await this.ctx.resume();
      this.ctx.onstatechange = function () {
        if (generation === self.generation && self.ctx && self.ctx.state !== "running")
          self.stop("microphone context suspended");
      };
      await this.ctx.audioWorklet.addModule("/voice/mic_worklet.js");
      if (generation !== this.generation) return;
      var id = crypto.randomUUID().replace(/-/g, "");
      this.captureId = id;
      var rate = this.ctx.sampleRate;
      var seq = 0, offset = 0;
      this.node = new AudioWorkletNode(this.ctx, "copilot-microphone");
      this.node.port.onmessage = function (event) {
        if (generation !== self.generation) return;
        var socket = self.getSocket();
        if (event.data.error || !socket || socket !== ws || socket.readyState !== 1 ||
            socket.bufferedAmount > 65536 || self.ctx.state !== "running") {
          self.stop(event.data.error || "microphone disconnected/backpressured/suspended");
          return;
        }
        var bytes = new Uint8Array(event.data);
        socket.send(JSON.stringify({v: 1, type: "voice.mic.chunk", capture_id: id,
          seq: seq++, sample_offset: offset, sample_rate: rate, pcm16: base64(bytes)}));
        offset += bytes.length / 2;
      };
      this.ctx.createMediaStreamSource(stream).connect(this.node);
      // Processor emits zeros to the destination: no audible microphone monitoring/feedback.
      this.node.connect(this.ctx.destination);
      stream.getTracks().forEach(function (track) {
        track.onended = function () { self.stop("microphone track ended"); };
        track.onmute = function () { self.stop("microphone track muted"); };
      });
      this.timer = setTimeout(function () { self.stop("180s capture limit"); }, 180000);
      this.status("MIC LIVE " + rate + " Hz — tap STOP", true);
    } catch (err) {
      if (generation === this.generation) this.stop(err.message);
    } finally {
      this.starting = false;
    }
  };
  Microphone.prototype.stop = function (reason) {
    this.generation++;
    clearTimeout(this.timer);
    if (this.node) this.node.disconnect();
    if (this.stream) this.stream.getTracks().forEach(function (t) { t.onended = null; t.onmute = null; t.stop(); });
    if (this.ctx) this.ctx.close().catch(function () {});
    var ws = this.getSocket();
    if (this.captureId && ws && ws.readyState === 1) ws.send(JSON.stringify({v: 1,
      type: "voice.mic.end", capture_id: this.captureId}));
    this.node = null; this.stream = null; this.ctx = null; this.captureId = null;
    this.status(reason || "MIC OFF", false);
  };
  root.CopilotTabletAudio = {NativePlayer: NativePlayer, Microphone: Microphone};
})(globalThis);
