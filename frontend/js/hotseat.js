// One device, two teams: the draft runs on the server (so the category's values stay
// hidden), the shot clock runs here. The team on the clock opens the slip with Draft a player.

import { api } from './api.js';
import { $ } from './dom.js';
import { loadLeague, makeEntries } from './names.js';
import {
  TEAM, criterionParts, finalText, renderDraft, renderNames, revealHint, setStatus, showDeal
} from './sheet.js';

const other = (mark) => (mark === 'X' ? 'O' : 'X');

export function readNames() {
  const clean = (id, fallback) => $(id).value.trim().slice(0, 16) || fallback;
  return { X: clean('name-p1', 'Player 1'), O: clean('name-p2', 'Player 2') };
}

export class HotSeatGame {
  constructor(ui, settings, names) {
    this.ui = ui;
    this.settings = settings;
    this.names = names;
    this.starter = 'X';
    this.state = null;
    this.busy = false;
    this.over = false;
  }

  async start() {
    const s = this.settings;
    this.state = await api.newDraft({
      league: s.league, mode: s.pickMode, style: s.style, reveal: s.reveal,
      starter: this.starter
    });
    if (s.pickMode === 'extreme') loadLeague(s.league).catch(() => {});
    this.over = false;
    this.dealing = true;
    this.ui.showGame({ room: null });
    renderNames(this.names);
    this.update();
    // The stat first; the shot clock starts once it's been seen
    this.closeDeal = showDeal(this.state, () => {
      this.dealing = false;
      this.closeDeal = null;
      if (this.state && this.state.status === 'in_progress') this.ui.clock.start(this.settings.clock);
    });
  }

  update() {
    const state = this.state;
    renderDraft(state, {
      names: this.names,
      canPick: state.status === 'in_progress',
      onRevealed: () => this.finish()
    });
    if (state.status !== 'in_progress') {
      this.ui.clock.start(0); // off: nothing left to time
      return;
    }
    const { kind, value } = criterionParts(state.current.criterion);
    setStatus(`${this.names[state.on_clock]} is on the clock: ${state.current.slot_name}, ` +
      `${kind.toLowerCase()} ${value}. Press Draft a player.`);
    if (!this.dealing) this.ui.clock.start(this.settings.clock);
  }

  openSlip() {
    const state = this.state;
    if (!state || state.status !== 'in_progress' || this.busy || this.ui.slip.isOpen) return;
    const mark = state.on_clock;
    const { kind, value } = criterionParts(state.current.criterion);
    const extreme = state.mode === 'extreme';
    this.ui.slip.open({
      title: `Team ${TEAM[mark]} · ${this.names[mark]} · pick ${state.pick_no}`,
      slot: state.current.slot_name,
      criterion: `${kind} ${value}`,
      hint: extreme
        ? 'Every player in the league is listed. Pick one who doesn’t fit, or is taken, and you get the shortest who does.'
        : `${state.pool.length} undrafted players fit, the best known first. ${revealHint(state)}`,
      entries: extreme ? loadLeague(state.league) : makeEntries(state.pool),
      minChars: extreme ? 2 : 1,
      browse: !extreme
    });
  }

  async pick(id) {
    if (this.busy || !this.state || this.state.status !== 'in_progress') return;
    this.busy = true;
    this.ui.clock.stop();
    try {
      this.state = await api.pick(this.state.id, this.state.on_clock, id);
    } catch (e) {
      setStatus(e.detail || 'That pick did not go through. Try again.', 'error');
      this.busy = false;
      this.ui.clock.start(this.settings.clock);
      return;
    }
    this.busy = false;
    this.update();
  }

  async clockExpired() {
    if (this.busy || !this.state || this.state.status !== 'in_progress') return;
    this.busy = true;
    this.ui.slip.close();
    try {
      this.state = await api.shotClock(this.state.id, this.state.on_clock);
    } finally {
      this.busy = false;
    }
    this.update();
  }

  slipCancelled() {
    setStatus(`${this.names[this.state.on_clock]} is on the clock. Press Draft a player when ready.`);
  }

  finish() {
    if (this.over) return;
    this.over = true;
    const w = this.state.winner;
    setStatus(w === 'draw' ? 'Dead even.' : `${this.names[w]} wins the draft.`, 'success');
    this.ui.showFinal(finalText(this.state, this.names), { rematch: 'Rematch' });
  }

  async rematch() {
    this.ui.hideFinal();
    this.starter = other(this.starter);
    await this.start();
  }

  leave() {
    if (this.closeDeal) {
      this.dealing = false;
      this.closeDeal();
    }
    this.ui.clock.stop();
    this.state = null;
  }
}
