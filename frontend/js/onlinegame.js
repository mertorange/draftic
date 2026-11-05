// An online room: the server owns the draft and the shot clock; this follows its snapshots,
// shows the lobby until both teams are ready; on this seat's pick, Draft a player opens the slip.

import { $, escapeHtml } from './dom.js';
import { loadLeague, makeEntries } from './names.js';
import { RoomConnection } from './online.js';
import {
  TEAM, criterionParts, finalText, renderDraft, renderNames, revealHint, setPresence, setStatus, showDeal
} from './sheet.js';

export function describeSettings(s) {
  return [
    s.league === 'nba' ? 'NBA' : 'EuroLeague',
    s.style === 'mixed' ? 'mixed criteria' : 'teams and countries',
    s.mode === 'extreme' ? 'extreme search' : 'eligible players only',
    'a random stat to win on',
    s.reveal === 'live' ? 'numbers shown as you go' : 'numbers shown after the last pick',
    s.clock ? `${s.clock} sec shot clock` : 'no shot clock'
  ].join(' · ');
}

export class OnlineGame {
  constructor(ui, code, name) {
    this.ui = ui;
    this.code = code;
    this.name = name;
    this.room = null;
    this.mine = null;
    this.inGame = false;
    this.finished = null;      // draft id whose final slip has been shown
    this.dealt = null;         // draft id whose stat reveal has been shown
    this.conn = new RoomConnection(code, name, {
      onRoom: (room) => this.onRoom(room),
      onError: (reason) => this.onError(reason),
      onStatus: (status) => this.onStatus(status)
    });
  }

  start() {
    this.ui.showLobby(this.code);
    this.conn.open();
  }

  get names() {
    const names = { X: 'Team A', O: 'Team B' };
    for (const seat of this.room ? this.room.seats : []) names[seat.mark] = seat.name;
    return names;
  }

  seat(mark) {
    return this.room.seats.find(s => s.mark === mark) || null;
  }

  onRoom(room) {
    this.room = room;
    this.mine = this.conn.mark;
    if (!room.draft) {
      this.renderLobby();
      return;
    }
    const state = room.draft;
    if (!this.inGame) {
      this.inGame = true;
      this.ui.showGame({ room: this.code });
    }
    const names = this.names;
    renderNames(names);
    ['X', 'O'].forEach(mark => {
      const seat = this.seat(mark);
      setPresence(mark, Boolean(seat && seat.connected));
    });

    // A draft that has just opened: its stat first (not after a reload mid-draft)
    if (this.dealt !== state.id) {
      this.dealt = state.id;
      if (!state.last && state.status === 'in_progress') {
        this.closeDeal = showDeal(state, () => { this.closeDeal = null; }, 5000);
      }
    }

    const myPick = state.status === 'in_progress' && state.on_clock === this.mine;
    renderDraft(state, { names, canPick: myPick, mine: this.mine, onRevealed: () => this.finish() });

    if (state.status !== 'in_progress') {
      this.ui.clock.follow(null, 0); // off: nothing left to time
      this.ui.slip.close();
      this.renderFinalWaiting();
      return;
    }
    if (this.finished && this.finished !== state.id) this.ui.hideFinal(); // a rematch began

    this.ui.clock.follow(room.ms_left, room.settings.clock);
    const { kind, value } = criterionParts(state.current.criterion);
    if (myPick) {
      setStatus(`Your pick: ${state.current.slot_name}, ${kind.toLowerCase()} ${value}. Press Draft a player.`);
    } else {
      this.ui.slip.close();
      const seat = this.seat(state.on_clock);
      const away = seat && !seat.connected ? ' (offline: the shot clock keeps running)' : '';
      setStatus(`${names[state.on_clock]} is picking${away}.`);
    }
  }

  openSlip() {
    const state = this.room && this.room.draft;
    if (!state || state.status !== 'in_progress' || state.on_clock !== this.mine || this.ui.slip.isOpen) return;
    const { kind, value } = criterionParts(state.current.criterion);
    const extreme = state.mode === 'extreme';
    this.ui.slip.open({
      title: `Team ${TEAM[this.mine]} · your pick · ${state.pick_no}`,
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

  pick(id) {
    this.conn.send('pick', { id });
  }

  clockExpired() {
    // The server calls the shot clock
  }

  slipCancelled() {
    setStatus('Still your pick. Press Draft a player when ready.');
  }

  finish() {
    const state = this.room.draft;
    if (this.finished === state.id) return;
    this.finished = state.id;
    const w = state.winner;
    setStatus(w === 'draw' ? 'Dead even.' : w === this.mine ? 'You win the draft.' : `${this.names[w]} wins the draft.`,
      'success');
    this.ui.showFinal(finalText(state, this.names, this.mine), { rematch: 'Rematch' });
    this.renderFinalWaiting();
  }

  renderFinalWaiting() {
    if (!this.room || !this.room.draft || this.finished !== this.room.draft.id) return;
    const me = this.seat(this.mine);
    const them = this.seat(this.mine === 'X' ? 'O' : 'X');
    const button = $('btn-rematch');
    let text = '';
    if (!them || !them.connected) {
      text = 'Your opponent has left the room.';
      button.disabled = true;
    } else if (me && me.rematch) {
      text = `Waiting for ${them.name} to accept the rematch...`;
      button.disabled = true;
    } else {
      text = them.rematch ? `${them.name} wants a rematch.` : '';
      button.disabled = false;
    }
    $('go-waiting').textContent = text;
  }

  rematch() {
    this.conn.send('rematch');
  }

  ready() {
    this.conn.send('ready');
  }

  renderLobby() {
    const room = this.room;
    this.ui.showLobby(this.code);
    $('lobby-settings').textContent = describeSettings(room.settings);
    $('lobby-seats').innerHTML = ['X', 'O'].map(mark => {
      const seat = this.seat(mark);
      const you = mark === this.mine ? ' <small>(you)</small>' : '';
      const name = seat ? `<span class="seat-name">${escapeHtml(seat.name)}${you}</span>`
        : '<span class="seat-name empty">Open seat</span>';
      const state = !seat ? '' : !seat.connected ? 'Offline' : seat.ready ? 'Ready' : 'Not ready';
      return `<li class="${seat && seat.ready ? 'is-ready' : ''}"><b class="ink-${mark.toLowerCase()}">${TEAM[mark]}</b>` +
        `${name}<span class="seat-state">${state}</span></li>`;
    }).join('');
    const me = this.seat(this.mine);
    const full = room.seats.length === 2;
    $('btn-ready').disabled = !full || !me || me.ready;
    $('lobby-hint').textContent = !full ? 'Send the link or the code to your opponent.'
      : me && me.ready ? 'Waiting for your opponent to be ready.' : 'Both here. Ready when you are.';
  }

  onError(reason) {
    if (!this.conn.welcomed) {
      this.ui.showMenu(reason);
      return;
    }
    if (this.inGame) setStatus(reason, 'error');
    else this.ui.showLobbyError(reason);
  }

  onStatus(status) {
    if (status === 'reconnecting') {
      if (this.inGame) setStatus('Connection lost. Reconnecting...', 'error');
    } else if (status === 'closed' && !this.conn.leaving) {
      if (this.inGame) setStatus('Lost the connection to the room. Reload the page to get back in.', 'error');
      else this.ui.showLobbyError('Lost the connection to the room.');
    }
  }

  leave() {
    if (this.closeDeal) this.closeDeal();
    this.ui.clock.stop();
    this.conn.leave();
  }
}
