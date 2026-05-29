// Audio plumbing for the live voice assistant. Adapted from the proven
// pattern in recruiter-ai-interview-platform, trimmed to audio-only (no
// camera, no integrity analysis): PCM playback of Gemini audio on the way in,
// and mic capture + downsample to 16kHz PCM on the way out.

// PCMPlayer queues base64-encoded PCM chunks and schedules them on a single
// AudioContext timeline so successive chunks play gap-free. onLevel emits a
// 0..1 volume hint for the UI meter, dropping to 0 when the queue drains.
export class PCMPlayer {
  private ctx: AudioContext | null = null;
  private nextStartTime = 0;
  private readonly leadTimeSeconds = 0.12;
  private readonly activeSources = new Set<AudioBufferSourceNode>();
  private readonly levelResetTimers = new Set<number>();

  constructor(private readonly onLevel: (level: number) => void) {}

  async playBase64PCM(base64PCM: string, mime: string): Promise<void> {
    const { sampleRate } = parseAudioMIME(mime);
    const ctx = this.ensureContext();
    if (ctx.state === "suspended") {
      await ctx.resume();
    }

    const bytes = decodeBase64(base64PCM);
    const pcm = new Int16Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
    const floatData = new Float32Array(pcm.length);
    let sumSquares = 0;
    for (let index = 0; index < pcm.length; index += 1) {
      const sample = (pcm[index] ?? 0) / 32768;
      floatData[index] = sample;
      sumSquares += sample * sample;
    }
    this.onLevel(Math.min(1, Math.sqrt(sumSquares / Math.max(floatData.length, 1)) * 3));

    const buffer = ctx.createBuffer(1, floatData.length, sampleRate);
    buffer.copyToChannel(floatData, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.onended = () => {
      this.activeSources.delete(source);
      if (this.activeSources.size === 0) {
        this.onLevel(0);
      }
    };

    const startAt = Math.max(ctx.currentTime + this.leadTimeSeconds, this.nextStartTime);
    this.activeSources.add(source);
    source.start(startAt);
    this.nextStartTime = startAt + buffer.duration;

    const resetTimer = window.setTimeout(() => {
      this.levelResetTimers.delete(resetTimer);
      if (this.activeSources.size === 0) {
        this.onLevel(0);
      }
    }, Math.max(120, Math.round((startAt - ctx.currentTime + buffer.duration) * 1000)));
    this.levelResetTimers.add(resetTimer);
  }

  // interrupt stops all scheduled playback — used when Gemini reports a
  // barge-in so stale audio doesn't keep talking over the user.
  interrupt() {
    for (const timer of this.levelResetTimers) {
      window.clearTimeout(timer);
    }
    this.levelResetTimers.clear();
    for (const source of this.activeSources) {
      try {
        source.stop();
      } catch {
        // Ignore nodes that already ended between iteration and stop().
      }
    }
    this.activeSources.clear();
    this.nextStartTime = this.ctx ? this.ctx.currentTime + this.leadTimeSeconds : 0;
    this.onLevel(0);
  }

  dispose() {
    this.interrupt();
    if (this.ctx) {
      void this.ctx.close();
      this.ctx = null;
    }
  }

  private ensureContext(): AudioContext {
    if (!this.ctx) {
      this.ctx = new AudioContext({ latencyHint: "interactive" });
      this.nextStartTime = this.ctx.currentTime + this.leadTimeSeconds;
    }
    return this.ctx;
  }
}

// PCMRecorder captures the mic, downsamples to 16kHz mono PCM, and emits each
// chunk as an ArrayBuffer. ScriptProcessorNode is used deliberately —
// AudioWorklet is lower-latency but adds a worklet-loading dance this surface
// doesn't need.
export class PCMRecorder {
  private ctx: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private stream: MediaStream | null = null;

  constructor(
    private readonly callbacks: {
      onChunk: (chunk: ArrayBuffer) => void;
      onLevel: (level: number) => void;
    },
  ) {}

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    this.ctx = new AudioContext();
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    this.processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      const downsampled = downsampleBuffer(input, event.inputBuffer.sampleRate, 16000);
      const pcm = floatTo16BitPCM(downsampled);
      this.callbacks.onLevel(calculateLevel(input));
      this.callbacks.onChunk(pcm.buffer.slice(0) as ArrayBuffer);
    };
    this.source.connect(this.processor);
    this.processor.connect(this.ctx.destination);
  }

  stop() {
    this.processor?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.ctx) {
      void this.ctx.close();
    }
    this.processor = null;
    this.source = null;
    this.stream = null;
    this.ctx = null;
  }
}

function downsampleBuffer(buffer: Float32Array, inputSampleRate: number, targetSampleRate: number): Float32Array {
  if (targetSampleRate >= inputSampleRate) {
    return buffer;
  }
  const ratio = inputSampleRate / targetSampleRate;
  const length = Math.round(buffer.length / ratio);
  const result = new Float32Array(length);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let index = offsetBuffer; index < nextOffsetBuffer && index < buffer.length; index += 1) {
      accum += buffer[index] ?? 0;
      count += 1;
    }
    result[offsetResult] = count > 0 ? accum / count : 0;
    offsetResult += 1;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function floatTo16BitPCM(buffer: Float32Array): Int16Array {
  const output = new Int16Array(buffer.length);
  for (let index = 0; index < buffer.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, buffer[index] ?? 0));
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

function calculateLevel(buffer: Float32Array): number {
  let sumSquares = 0;
  for (let index = 0; index < buffer.length; index += 1) {
    const sample = buffer[index] ?? 0;
    sumSquares += sample * sample;
  }
  return Math.min(1, Math.sqrt(sumSquares / Math.max(buffer.length, 1)) * 3);
}

function decodeBase64(value: string): Uint8Array {
  const binary = window.atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function parseAudioMIME(mime: string): { sampleRate: number } {
  const match = /rate=(\d+)/.exec(mime);
  return { sampleRate: match ? Number(match[1]) : 24000 };
}
