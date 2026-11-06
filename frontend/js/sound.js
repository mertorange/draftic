// Sound effects: short cues synthesised with the Web Audio API, plus the pick sounds, which are
// pre-rendered files (sounds/pick-*.wav, made by backend/scripts/make_pick_sounds.py).

const MUTE_KEY = 'draftic:muted';
// name -> [file, volume]
const FILES = {
  chime: ['pick-chime.wav', 0.5],  // a team goes on the clock
  good: ['pick-good.wav', 0.45],   // a pick that fits
  bad: ['pick-bad.wav', 0.45]      // a wrong pick, or the shot clock ran out
};

class SoundFX {
  constructor() {
    this.ctx = null;
    this.files = {};
    this.muted = false;
    try {
      this.muted = localStorage.getItem(MUTE_KEY) === '1';
    } catch (e) {}
  }

  /** Remembered per browser, so a muted player stays muted on the next visit. */
  setMuted(muted) {
    this.muted = muted;
    try {
      localStorage.setItem(MUTE_KEY, muted ? '1' : '0');
    } catch (e) {}
  }

  /** The audio context, or nothing while muted (no context is even created then). */
  ready() {
    if (this.muted) return null;
    this.init();
    return this.ctx;
  }

  init() {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) this.ctx = new AudioCtx();
    }
    if (this.ctx && this.ctx.state === 'suspended') this.ctx.resume();
  }

  /** Fetch the pick sounds ahead of the first pick, so they aren't late waiting on the network. */
  preload() {
    if (this.muted) return;
    for (const name of Object.keys(FILES)) this.file(name);
  }

  file(name) {
    if (!this.files[name]) {
      const [path, volume] = FILES[name];
      const audio = new Audio(new URL(`../sounds/${path}`, import.meta.url).href);
      audio.preload = 'auto';
      audio.volume = volume;
      this.files[name] = audio;
    }
    return this.files[name];
  }

  playFile(name) {
    try {
      if (this.muted) return;
      const audio = this.file(name);
      audio.currentTime = 0;
      const playing = audio.play();
      if (playing) playing.catch(() => {});  // blocked before any click: stay quiet
    } catch (e) {}
  }

  // The draft-night jingle, as a team goes on the clock
  playOnClock() { this.playFile('chime'); }

  // The pick's verdict: it fits, or it's a turnover (wrong player or the shot clock ran out)
  playPickGood() { this.playFile('good'); }
  playPickBad() { this.playFile('bad'); }

  // Warning beep for last 5 seconds of shot clock
  playClockBeep() {
    try {
      if (!this.ready()) return;
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = 'square';
      osc.frequency.setValueAtTime(880, this.ctx.currentTime);
      gain.gain.setValueAtTime(0.08, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.08);
      osc.connect(gain);
      gain.connect(this.ctx.destination);
      osc.start();
      osc.stop(this.ctx.currentTime + 0.08);
    } catch (e) {}
  }

  // Arena buzzer horn (dual-tone sawtooth)
  playArenaBuzzer() {
    try {
      if (!this.ready()) return;
      const t = this.ctx.currentTime;
      const osc1 = this.ctx.createOscillator();
      const osc2 = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc1.type = 'sawtooth';
      osc2.type = 'sawtooth';
      osc1.frequency.setValueAtTime(146.83, t); // D3
      osc2.frequency.setValueAtTime(220.00, t); // A3

      gain.gain.setValueAtTime(0.25, t);
      gain.gain.setValueAtTime(0.25, t + 0.5);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.7);

      osc1.connect(gain);
      osc2.connect(gain);
      gain.connect(this.ctx.destination);

      osc1.start(t);
      osc2.start(t);
      osc1.stop(t + 0.7);
      osc2.stop(t + 0.7);
    } catch (e) {}
  }

  // Win fanfare
  playWin() {
    try {
      if (!this.ready()) return;
      [523.25, 659.25, 783.99, 1046.50].forEach((freq, idx) => {
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = freq;
        const start = this.ctx.currentTime + idx * 0.12;
        gain.gain.setValueAtTime(0.15, start);
        gain.gain.exponentialRampToValueAtTime(0.001, start + 0.35);
        osc.connect(gain);
        gain.connect(this.ctx.destination);
        osc.start(start);
        osc.stop(start + 0.35);
      });
    } catch (e) {}
  }
}

export const sfx = new SoundFX();
