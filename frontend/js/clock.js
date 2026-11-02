// The shot clock: a countdown driving a seven-segment display and the slip's mini clock.
// The same seven-segment digits show each team's total on the scoreboard (see sheet.js).

import { sfx } from './sound.js';

const SEGMENTS = {
  a: '5,1 19,1 21,3 19,5 5,5 3,3',
  b: '19,5 21,3 23,5 23,19 21,21 19,19',
  c: '19,25 21,23 23,25 23,39 21,41 19,39',
  d: '5,39 19,39 21,41 19,43 5,43 3,41',
  e: '1,25 3,23 5,25 5,39 3,41 1,39',
  f: '1,5 3,3 5,5 5,19 3,21 1,19',
  g: '5,20 19,20 21,22 19,24 5,24 3,22'
};
const DIGITS = ['abcdef', 'bc', 'abdeg', 'abcdg', 'bcfg', 'acdfg', 'acdefg', 'abc', 'abcdefg', 'abcdfg'];
const WARNING_SECONDS = 5;

/** Lays out `slots` seven-segment digits in an svg, all segments off. */
export function buildSegments(svg, slots) {
  let html = '';
  for (let slot = 0; slot < slots; slot++) {
    html += `<g transform="translate(${3 + slot * 27} 1) skewX(-6)">`;
    Object.entries(SEGMENTS).forEach(([seg, pts]) => {
      html += `<polygon data-slot="${slot}" data-seg="${seg}" points="${pts}"/>`;
    });
    html += '</g>';
  }
  svg.setAttribute('viewBox', `0 0 ${slots * 27} 46`);
  svg.innerHTML = html;
}

/** Lights the segments for a number, right-aligned without leading zeros (' 9', not '09'). */
export function showNumber(svg, value) {
  const slots = svg.querySelectorAll('g').length;
  const text = String(value).padStart(slots, ' ');
  svg.querySelectorAll('polygon').forEach(p => {
    const ch = text[Number(p.dataset.slot)];
    p.classList.toggle('on', ch !== ' ' && DIGITS[Number(ch)].includes(p.dataset.seg));
  });
}

/** Every slot showing a dash: a value the board doesn't know yet. */
export function showDashes(svg) {
  svg.querySelectorAll('polygon').forEach(p => p.classList.toggle('on', p.dataset.seg === 'g'));
}

export class ShotClock {
  /**
   * @param {HTMLElement} panel  wrapper shown on the scorer's table
   * @param {SVGElement} digits  the seven-segment svg inside it
   * @param {HTMLElement} mini   the small readout on the player slip
   * @param {() => void} onExpire called once when the clock hits zero
   */
  constructor(panel, digits, mini, onExpire) {
    this.panel = panel;
    this.digits = digits;
    this.mini = mini;
    this.onExpire = onExpire;
    this.seconds = 0;
    this.length = 0;
    this.timer = null;
  }

  start(length) {
    this.stop();
    this.length = length;
    if (length <= 0) {
      this.panel.classList.add('off');
      this.mini.textContent = '';
      return;
    }
    this.panel.classList.remove('off');
    const slots = length >= 100 ? 3 : 2;
    if (this.digits.querySelectorAll('g').length !== slots) this.build(slots);
    this.seconds = length;
    this.render();

    this.timer = setInterval(() => {
      this.seconds--;
      this.render();
      if (this.seconds <= WARNING_SECONDS && this.seconds > 0) sfx.playClockBeep();
      if (this.seconds <= 0) {
        this.stop();
        this.onExpire();
      }
    }, 1000);
  }

  /**
   * Online play: the server owns the clock and sends how much of the turn is left;
   * this only counts down on screen. Expiry is the server's call, so no callback.
   */
  follow(msLeft, length) {
    this.stop();
    this.length = length;
    if (!length || msLeft == null) {
      this.panel.classList.add('off');
      this.mini.textContent = '';
      return;
    }
    this.panel.classList.remove('off');
    const slots = length >= 100 ? 3 : 2;
    if (this.digits.querySelectorAll('g').length !== slots) this.build(slots);
    const deadline = performance.now() + msLeft;
    let shown = null;
    const tick = () => {
      const seconds = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
      if (seconds === shown) return;
      // Snapshots re-sync the clock mid-second; beep only when the number really changes
      const changed = seconds !== this.seconds;
      shown = seconds;
      this.seconds = seconds;
      this.render();
      if (changed && seconds <= WARNING_SECONDS && seconds > 0) sfx.playClockBeep();
    };
    tick();
    this.timer = setInterval(tick, 200);
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  build(slots) {
    buildSegments(this.digits, slots);
    this.digits.classList.toggle('three', slots === 3);
  }

  render() {
    const value = Math.max(this.seconds, 0);
    showNumber(this.digits, value);
    this.mini.textContent = value;
    const warn = value <= WARNING_SECONDS;
    this.panel.classList.toggle('warning', warn);
    this.mini.classList.toggle('warning', warn);
  }
}
