/* PCM16 mono; no resampling, dropped-block padding, or microphone monitoring. */
"use strict";
class CopilotMicrophone extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new ArrayBuffer(4096);
    this.view = new DataView(this.buffer);
    this.used = 0;
    this.nextFrame = null;
    this.failed = false;
  }
  process(inputs) {
    if (this.failed) return false;
    var input = inputs[0] && inputs[0][0];
    if (!input || !input.length || (this.nextFrame !== null && currentFrame !== this.nextFrame)) {
      this.failed = true;
      this.port.postMessage({error: "microphone audio render gap/no input"});
      return false;
    }
    this.nextFrame = currentFrame + input.length;
    for (var i = 0; i < input.length; i++) {
      if (!Number.isFinite(input[i])) {
        this.failed = true;
        this.port.postMessage({error: "microphone nonfinite sample"});
        return false;
      }
      var x = Math.max(-1, Math.min(1, input[i]));
      this.view.setInt16(this.used * 2, Math.round(x * (x < 0 ? 32768 : 32767)), true);
      this.used++;
      if (this.used === 2048) {
        this.port.postMessage(this.buffer, [this.buffer]);
        this.buffer = new ArrayBuffer(4096);
        this.view = new DataView(this.buffer);
        this.used = 0;
      }
    }
    return true;
  }
}
registerProcessor("copilot-microphone", CopilotMicrophone);
