// Draftić: a two-team draft on a scorer's sheet, scored on a stat dealt at random. This module owns the menu, the
// screens and the dialogs; the draft itself runs in a controller: HotSeatGame (one device)
// or OnlineGame (a room shared over a WebSocket).

import { api } from './api.js';
import { ShotClock } from './clock.js';
import { $, closeModal, escapeHtml, isOpen, openModal } from './dom.js';
import { HotSeatGame, readNames } from './hotseat.js';
import { hasSeat } from './online.js';
import { OnlineGame, describeSettings } from './onlinegame.js';
import { PlayerSlip } from './slip.js';
import { sfx } from './sound.js';

let active = null; // the running controller

const screens = { menu: $('screen-menu'), join: $('screen-join'), lobby: $('screen-lobby'), game: $('screen-game') };
const modals = { gameover: $('modal-gameover'), rules: $('modal-rules-popup') };
const NAME_KEY = 'draftic:name';

const ui = {
  clock: new ShotClock($('shotclock-display'), $('clock-digits'), $('modal-clock-num'),
    () => active && active.clockExpired()),
  slip: new PlayerSlip((id) => active && active.pick(id), () => active && active.slipCancelled()),
  showGame,
  showLobby,
  showLobbyError: (reason) => { $('lobby-error').textContent = reason; },
  showFinal,
  hideFinal: () => closeModal(modals.gameover),
  showMenu
};

// ---------- Screens ----------

function showScreen(name) {
  Object.entries(screens).forEach(([key, el]) => el.classList.toggle('hidden', key !== name));
}

function showGame({ room }) {
  closeModal(modals.gameover);
  $('meta-room-wrap').hidden = !room;
  $('meta-room').textContent = room || '';
  showScreen('game');
}

function showLobby(code) {
  if (!screens.lobby.classList.contains('hidden')) return;
  $('lobby-code').textContent = code;
  $('lobby-link').textContent = `${location.origin}/?room=${code}`;
  $('lobby-error').textContent = '';
  showScreen('lobby');
}

function showMenu(error = '') {
  if (active) active.leave();
  active = null;
  ui.slip.close();
  closeModal(modals.gameover);
  history.replaceState(null, '', location.pathname);
  $('menu-error').textContent = error;
  showScreen('menu');
}

function showFinal({ title, score, desc, stamp }) {
  $('go-stamp').className = `stamp ${stamp}`;
  $('go-title').textContent = title;
  $('go-score').innerHTML = score;
  $('go-desc').textContent = desc;
  $('go-waiting').textContent = '';
  $('btn-rematch').disabled = false;
  openModal(modals.gameover);
}

// ---------- Menu ----------

function readSettings(form) {
  const data = new FormData(form);
  return {
    mode: data.get('mode'),
    league: data.get('league'),
    style: data.get('style') || 'classic',
    reveal: data.get('reveal') || 'end',
    pickMode: data.get('pick_mode') || 'eligible',
    clock: parseInt(data.get('clock'), 10) || 0
  };
}

let leagues = null; // what /api/leagues says each league has, once it's here

function syncMenuMode() {
  const data = new FormData($('setup-form'));
  const mode = data.get('mode');
  $('setup-form').dataset.mode = mode;
  $('btn-launch-game').textContent = mode === 'online' ? 'Open a draft room' : 'Start the draft';
  // Online rooms always run a shot clock (a draft must never wait on a player who has gone)
  const off = $('setup-form').querySelector('input[name=clock][value="0"]');
  if (mode === 'online' && off.checked) {
    $('setup-form').querySelector('input[name=clock][value="60"]').checked = true;
  }
  renderStatList(data.get('league'));
}

/** The stats the chosen league can deal, from the server, since each league has its own. */
function renderStatList(league) {
  const list = $('stat-list');
  if (!leagues || !leagues[league]) {
    list.innerHTML = '';
    return;
  }
  list.innerHTML = leagues[league].categories
    .map(c => `<li class="${c.kind}">${escapeHtml(c.label)}</li>`).join('');
}

function savedName() {
  try {
    return localStorage.getItem(NAME_KEY) || '';
  } catch (e) {
    return '';
  }
}

function onlineName(input = $('name-online')) {
  const name = input.value.trim().slice(0, 16) || 'Player';
  try {
    localStorage.setItem(NAME_KEY, name);
  } catch (e) {}
  return name;
}

async function startController(controller) {
  if (active) active.leave();
  active = controller;
  try {
    await controller.start();
  } catch (e) {
    showMenu(e.detail || 'Could not reach the server. Is it running?');
  }
}

async function createRoom(settings) {
  try {
    const { code } = await api.createRoom({
      league: settings.league, mode: settings.pickMode, style: settings.style,
      reveal: settings.reveal, clock: settings.clock
    });
    history.replaceState(null, '', `?room=${code}`);
    startController(new OnlineGame(ui, code, onlineName()));
  } catch (e) {
    $('menu-error').textContent = e.detail || 'Could not create a room.';
  }
}

function joinRoom() {
  const code = $('join-code').value.trim().toUpperCase();
  if (code.length !== 5) {
    $('menu-error').textContent = 'A room code has five letters.';
    return;
  }
  history.replaceState(null, '', `?room=${code}`);
  startController(new OnlineGame(ui, code, onlineName()));
}

/** An invite link: the room's settings are fixed, so just a name and Ready. */
async function showJoin(code) {
  showScreen('join');
  $('join-code-title').textContent = code;
  $('join-name').value = savedName();
  $('join-error').textContent = '';
  try {
    const info = await api.roomInfo(code);
    $('join-settings').textContent = describeSettings(info.settings);
    if (info.players >= 2) {
      $('join-settings').textContent = 'This room is full.';
      $('btn-join-menu').hidden = false;
      $('join-name-field').hidden = true;
      return;
    }
    $('btn-join-ready').disabled = false;
    $('join-name').focus();
  } catch (e) {
    $('join-settings').textContent = 'No room with that code. It may have closed.';
    $('btn-join-menu').hidden = false;
    $('join-name-field').hidden = true;
  }
}

function joinAndReady() {
  const code = $('join-code-title').textContent;
  const game = new OnlineGame(ui, code, onlineName($('join-name')));
  startController(game);
  // Ready as soon as the seat is ours: the joiner already said yes on this page
  const ready = setInterval(() => {
    if (active !== game) return clearInterval(ready);
    if (game.room && game.room.seats.length === 2) {
      clearInterval(ready);
      game.ready();
    }
  }, 150);
}

function leaveToMenu() {
  showMenu();
}

// ---------- Wiring ----------

function setupSound() {
  const btn = $('btn-sound');
  const sync = () => {
    btn.classList.toggle('muted', sfx.muted);
    btn.setAttribute('aria-pressed', String(!sfx.muted));
    $('sound-label').textContent = sfx.muted ? 'Muted' : 'Sound';
  };
  btn.addEventListener('click', () => {
    sfx.setMuted(!sfx.muted);
    sync();
  });
  sync();
}

function setup() {
  const form = $('setup-form');
  form.querySelectorAll('input[name=mode], input[name=league], input[name=clock]')
    .forEach(input => input.addEventListener('change', syncMenuMode));
  api.leagues().then(data => {
    leagues = data;
    syncMenuMode();
  }).catch(() => {});
  $('name-online').value = savedName();

  const invited = (new URLSearchParams(location.search).get('room') || '').toUpperCase();
  if (invited) {
    form.querySelector('input[name=mode][value=online]').checked = true;
    $('join-code').value = invited;
  }
  syncMenuMode();
  if (invited && hasSeat(invited)) {
    startController(new OnlineGame(ui, invited, onlineName())); // a reload: back to the seat
  } else if (invited) {
    showJoin(invited);
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const settings = readSettings(form);
    $('menu-error').textContent = '';
    if (settings.mode === 'online') createRoom(settings);
    else startController(new HotSeatGame(ui, settings, readNames()));
  });
  $('btn-join-room').addEventListener('click', joinRoom);
  $('join-code').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      joinRoom();
    }
  });
  $('btn-join-ready').addEventListener('click', joinAndReady);
  $('join-name').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !$('btn-join-ready').disabled) {
      e.preventDefault();
      joinAndReady();
    }
  });
  $('btn-join-menu').addEventListener('click', () => showMenu());

  $('btn-ready').addEventListener('click', () => {
    if (active && active.ready) {
      active.ready();
      $('btn-ready').disabled = true;
    }
  });
  $('btn-lobby-leave').addEventListener('click', leaveToMenu);
  $('btn-copy-link').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText($('lobby-link').textContent);
      $('btn-copy-link').textContent = 'Copied';
      setTimeout(() => { $('btn-copy-link').textContent = 'Copy link'; }, 1500);
    } catch (e) {}
  });

  $('btn-draft').addEventListener('click', () => active && active.openSlip());
  $('btn-game-exit').addEventListener('click', leaveToMenu);
  $('btn-game-rules').addEventListener('click', () => openModal(modals.rules));
  $('btn-ack-rules').addEventListener('click', () => closeModal(modals.rules));

  $('btn-return-menu-go').addEventListener('click', leaveToMenu);
  $('btn-see-rosters').addEventListener('click', () => closeModal(modals.gameover));
  $('btn-rematch').addEventListener('click', () => {
    if (!active) return;
    active.rematch();
    if (active instanceof OnlineGame) active.renderFinalWaiting();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isOpen(modals.rules)) closeModal(modals.rules);
  });
  setupSound();
}

setup();
