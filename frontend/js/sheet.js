// Drawing the draft sheet from a draft state (the server's Draft.public()): the scoreboard
// with each team's running total, the draft board (every pick in order, like the arena's),
// the round card, the last pick read out, and the reveal of the category's values.
//
// Values either show as each player is drafted (reveal "live") or all at the end ("end"),
// tile by tile. Either way the winner is only called once every value is on the board.

import { buildSegments, showDashes, showNumber } from './clock.js';
import { $, escapeHtml } from './dom.js';
import { sfx } from './sound.js';

export const TEAM = { X: 'A', O: 'B' };
const MARKS = ['X', 'O'];
const KIND_LABELS = { team: 'Played for', country: 'Born in', era: 'Played in the', college: 'College' };
const REVEAL_STEP = 170;   // ms between tiles lighting up at the end
const CHIME_AFTER_VERDICT = 700;  // ms from a pick's verdict sound to the next team's jingle
function ORDINAL(n) {
  const suffix = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (suffix[(v - 20) % 10] || suffix[v] || suffix[0]);
}

let lastRound = null;      // `${draftId}:${round}`: deal the strip only when it changes
let lastPick = null;       // `${draftId}:${pickCount}`: write only the new pick on
let reveal = null;         // the final reveal: {id, lit: tiles shown so far, running: totals so far, done}
let revealTimers = [];
let chimeTimer = null;     // the next team's jingle, waiting for the verdict sound to ring

export function setStatus(msg, type = '') {
  const el = $('game-status-text');
  el.textContent = msg;
  el.className = 'status' + (type ? ` ${type}` : '');
}

export function renderNames(names) {
  $('text-name-x').textContent = names.X;
  $('text-name-o').textContent = names.O;
}

export function setPresence(mark, online) {
  $(`panel-${mark.toLowerCase()}`).classList.toggle('offline', !online);
}

/**
 * The stat reveal at the start of a draft. onGo runs once, when it's closed (the button,
 * Enter or Escape); autoClose closes it by itself after that many ms (online, where the
 * server's shot clock is already running).
 */
export function showDeal(state, onGo = () => {}, autoClose = 0) {
  const modal = $('modal-deal');
  const { label, kind, hint } = state.category;
  $('deal-stat').textContent = label;
  $('deal-hint').textContent = hint;
  const counted = state.league === 'nba' ? 'Counted over NBA regular seasons.' : 'Counted over EuroLeague games since 2000-01.';
  $('deal-scope').textContent = `${kind === 'career' ? `${counted} ` : ''}The higher team total wins.`;
  const button = $('btn-deal-go');
  button.textContent = autoClose ? 'Got it' : 'Start drafting';
  let timer = null;
  const close = () => {
    clearTimeout(timer);
    button.removeEventListener('click', start);
    modal.removeEventListener('keydown', onKey);
    modal.classList.remove('active');
    onGo();
  };
  // Closed to draft (not to leave the game): the first team is on the clock
  const start = () => {
    close();
    sfx.playOnClock();
  };
  const onKey = (e) => {
    if (e.key === 'Enter' || e.key === 'Escape') {
      e.preventDefault();
      start();
    }
  };
  button.addEventListener('click', start);
  modal.addEventListener('keydown', onKey);
  modal.classList.add('active');
  button.focus();
  if (autoClose) timer = setTimeout(start, autoClose);
  return close;
}

/** One line for the player slip: what the draft is scored on and when the numbers show. */
export function revealHint(state) {
  const stat = state.category.label.toLowerCase();
  return state.reveal === 'live'
    ? `Scored on ${stat}: each player's number shows once drafted.`
    : `Scored on ${stat}: the numbers stay hidden until the last pick.`;
}

/** A number for a tile: '43.5k' past ten thousand, so it fits next to the name. */
function tileNumber(value) {
  return value >= 10000 ? `${(value / 1000).toFixed(1)}k` : value.toLocaleString('en-US');
}

/** The same figure another way, for the tooltip: feet and inches, pounds. */
function otherUnits(value, category) {
  if (category.key === 'height') return ` (${feetInches(value)})`;
  if (category.key === 'weight') return ` (${Math.round(value * 2.2046)} lb)`;
  return '';
}

export function feetInches(cm) {
  const inches = Math.round(cm / 2.54);
  return `${Math.floor(inches / 12)}′${inches % 12}″`;
}

/** The criterion as the card shows it: a small kind line and the value. */
export function criterionParts(criterion) {
  const value = criterion.kind === 'era' ? `${criterion.value}s` : criterion.value;
  return { kind: KIND_LABELS[criterion.kind] || '', value };
}

/** A team's total on its scoreboard LED; null shows dashes (not known yet). */
function setTotal(mark, value, category) {
  const unit = $(`score-${mark.toLowerCase()}`);
  const digits = unit.querySelector('svg');
  const slots = Math.max(4, value === null ? 0 : String(value).length);
  if (digits.querySelectorAll('g').length !== slots) {
    buildSegments(digits, slots);
    digits.style.setProperty('--slots', slots);
  }
  const label = `Total ${category.label.toLowerCase()}`;
  if (value === null) {
    showDashes(digits);
    unit.setAttribute('aria-label', `${label} not shown yet`);
  } else {
    showNumber(digits, value);
    unit.setAttribute('aria-label', `${label}: ${value} ${category.unit}`);
  }
}

function markWinner(winner) {
  MARKS.forEach(mark => $(`score-${mark.toLowerCase()}`).classList.toggle('won', winner === mark));
}

/** True once the draft is over and every value is on the board: the result can be told. */
export function resultShown(state) {
  return state.status === 'final' && reveal !== null && reveal.id === state.id && reveal.done;
}

/**
 * @param {object} state  the draft
 * @param {object} opts   {names, canPick: bool, mine: mark|null, onRevealed: () => void}
 */
export function renderDraft(state, { names, canPick, mine = null, onRevealed = () => {} }) {
  const final = state.status === 'final';
  const pickCount = state.pick_no - (final ? 0 : 1);
  $('meta-league').textContent = state.league === 'nba' ? 'NBA' : 'EuroLeague';
  $('meta-mode').textContent = state.mode === 'extreme' ? 'Extreme' : 'Eligible only';
  $('meta-category').textContent = state.category.label;
  $('meta-reveal').textContent = state.reveal === 'live' ? 'As you go' : 'At the end';
  document.querySelectorAll('.total-label').forEach(el => {
    el.textContent = `Total ${state.category.label.toLowerCase()}`;
  });
  $('card-category').textContent = `Category · ${state.category.label}`;
  $('meta-round').textContent = final ? 'Final' : `${state.round + 1} of ${state.rounds}`;
  MARKS.forEach(mark => {
    $(`panel-${mark.toLowerCase()}`).classList.toggle('active-turn', state.on_clock === mark);
  });

  // A new draft: forget the last one's reveal
  if (reveal && reveal.id !== state.id) {
    revealTimers.forEach(clearTimeout);
    revealTimers = [];
    reveal = null;
  }

  const pickKey = `${state.id}:${pickCount}`;
  const newPick = lastPick !== null && lastPick !== pickKey && state.last;
  lastPick = pickKey;
  // Set the reveal up first, so the board and scoreboard below are drawn from it
  if (final && !reveal) startReveal(state, names, onRevealed);
  renderBoard(state, names, newPick ? state.last : null);
  renderTotals(state);
  renderCard(state, names, canPick, mine);
  renderAnnounce(state, names, newPick);

  if (newPick) {
    // The verdict now; then, once it's rung, the jingle for the team that's on the clock next
    if (state.last.turnover) sfx.playPickBad();
    else sfx.playPickGood();
    clearTimeout(chimeTimer);
    if (!final) chimeTimer = setTimeout(() => sfx.playOnClock(), CHIME_AFTER_VERDICT);
  }
}

/** The draft order: [mark, round] for picks 1..12 (A, B, then B, A, and so on). */
function pickOrder(state) {
  const order = [];
  for (let r = 0; r < state.rounds; r++) {
    const first = r % 2 === 0 ? state.starter : (state.starter === 'X' ? 'O' : 'X');
    order.push([first, r], [first === 'X' ? 'O' : 'X', r]);
  }
  return order;
}

/** 'Brandon Jennings' -> 'B. Jennings', as the arena board writes it; 'A.J. Price' stays. */
function boardName(name) {
  const parts = name.split(' ');
  if (parts.length < 2 || parts[0].includes('.')) return name;
  return `${parts[0][0]}. ${parts.slice(1).join(' ')}`;
}

/** How many tiles, in pick order, have their value showing right now. */
function tilesLit(state) {
  if (state.status !== 'final') return state.reveal === 'live' ? Infinity : 0;
  return reveal && reveal.id === state.id ? reveal.lit : 0;
}

function renderBoard(state, names, fresh) {
  const final = state.status === 'final';
  const done = state.pick_no - (final ? 0 : 1);
  $('board-league').textContent = `${state.league === 'nba' ? 'NBA' : 'EuroLeague'} draft`;
  $('board-round').textContent = final ? 'Final' : `Round ${state.round + 1}`;
  $('board-category').textContent = state.category.label;

  const order = pickOrder(state);
  $('board-picks').innerHTML = order.map(([mark, r], k) => {
    const pick = state.picks[mark][r];
    const now = !final && k === done;
    const classes = ['tile', mark.toLowerCase(), pick ? '' : now ? 'now' : 'upcoming',
      fresh && pick && fresh.mark === mark && fresh.round === r ? 'fresh' : ''].filter(Boolean).join(' ');
    const name = pick ? escapeHtml(boardName(pick.name)) : now ? 'On the clock' : '';
    const title = pick
      ? `Pick ${k + 1}: ${names[mark]} · ${state.slots[r]} · ${pick.criterion} · ${pick.name}` +
        (pick.turnover ? ` (turnover: ${pick.turnover})` : '')
      : `Pick ${k + 1}: ${names[mark]} · ${state.slots[r]}`;
    return `<li class="${classes}" title="${escapeHtml(title)}">` +
      `<span class="tile-no">${k + 1}</span><span class="tile-team">${TEAM[mark]}</span>` +
      `<span class="tile-name">${name}</span><span class="tile-side">` +
      (pick && pick.turnover ? '<span class="tile-to">TO</span>' : '') +
      `<span class="tile-slot">${state.slots[r]}</span><span class="tile-value" data-pick="${k}"></span>` +
      '</span></li>';
  }).join('');

  const lit = tilesLit(state);
  order.forEach(([mark, r], k) => {
    const pick = state.picks[mark][r];
    const isFresh = fresh && pick && fresh.mark === mark && fresh.round === r;
    if (pick && 'value' in pick && k < lit) lightTile(state, k, pick, isFresh);
  });
}

/** The scoreboard: running totals as you go, dashes until the end, counted up at the reveal. */
function renderTotals(state) {
  const final = state.status === 'final';
  if (final && reveal && reveal.id === state.id) {
    MARKS.forEach(mark => setTotal(mark, reveal.done ? state.totals[mark] : reveal.running[mark], state.category));
    markWinner(reveal.done ? state.winner : null);
    return;
  }
  const known = state.reveal === 'live' && state.totals;
  MARKS.forEach(mark => setTotal(mark, known ? state.totals[mark] : null, state.category));
  markWinner(null);
}

function renderCard(state, names, canPick, mine) {
  const card = $('round-card');
  const draftBtn = $('btn-draft');
  if (state.status === 'final') {
    const label = state.category.label.toLowerCase();
    $('card-pick').textContent = 'Draft complete';
    $('card-slot').textContent = String(state.rounds);
    $('card-slot-name').textContent = 'players a side';
    if (resultShown(state)) {
      $('card-kind').textContent = state.category.key === 'height' ? 'Taller roster' : `More ${label}`;
      const w = state.winner;
      $('card-crit').textContent = w === 'draw' ? 'Dead even' : `${names[w]} wins`;
    } else {
      $('card-kind').textContent = `All ${state.rounds * 2} picks are in`;
      $('card-crit').textContent = `Adding up the ${label}...`;
    }
    $('card-turn').textContent = '';
    draftBtn.hidden = true;
    return;
  }
  const key = `${state.id}:${state.round}`;
  if (lastRound !== key) {
    lastRound = key;
    card.classList.remove('dealt');
    void card.offsetWidth; // restart the animation
    card.classList.add('dealt');
  }
  const { kind, value } = criterionParts(state.current.criterion);
  $('card-pick').textContent = `Round ${state.round + 1} · ${ORDINAL(state.pick_no)} pick`;
  $('card-slot').textContent = state.current.slot;
  $('card-slot-name').textContent = state.current.slot_name;
  $('card-kind').textContent = kind;
  $('card-crit').textContent = value;
  const turn = $('card-turn');
  const who = mine === state.on_clock ? 'You are' : `${names[state.on_clock]} is`;
  turn.textContent = `${who} on the clock`;
  turn.className = `card-turn ${state.on_clock.toLowerCase()}`;
  draftBtn.hidden = !canPick;
}

function renderAnnounce(state, names, fresh) {
  const el = $('announce');
  const last = state.last;
  if (!last) {
    // Before the first pick: the stat this draft was dealt, the thing to draft for
    el.innerHTML = `The draft is open. Scored on<b>${escapeHtml(state.category.label)}</b>`;
    el.classList.remove('fresh');
    return;
  }
  const n = state.pick_no - (state.status === 'final' ? 0 : 1);
  const lead = last.turnover
    ? `<span class="to">${escapeHtml(capitalise(last.turnover))}.</span> With the ${ORDINAL(n)} pick, ${escapeHtml(names[last.mark])} gets`
    : `With the ${ORDINAL(n)} pick, ${escapeHtml(names[last.mark])} selects`;
  el.innerHTML = `${lead}<b class="${last.mark.toLowerCase()}">${escapeHtml(last.name)}</b>`;
  if (fresh) {
    el.classList.remove('fresh');
    void el.offsetWidth;
    el.classList.add('fresh');
  }
}

function capitalise(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** A pick's value on its tile; the full figure (with feet and inches) goes in the tooltip. */
function lightTile(state, k, pick, animate) {
  const cell = $('board-picks').querySelector(`.tile-value[data-pick="${k}"]`);
  if (!cell || cell.textContent) return;
  cell.textContent = tileNumber(pick.value);
  if (animate) cell.classList.add('lit');
  const tile = cell.closest('.tile');
  tile.classList.add('measured');
  tile.title += ` · ${pick.value.toLocaleString('en-US')} ${state.category.unit}${otherUnits(pick.value, state.category)}`;
}

/**
 * The end of the draft. Revealed at the end: the values light up tile by tile in pick order
 * while the scoreboard counts along. Revealed as you go: everything is already up, so just a
 * beat. Then the winner, and only then.
 */
function startReveal(state, names, done) {
  const order = pickOrder(state);
  const live = state.reveal === 'live';
  reveal = { id: state.id, lit: live ? order.length : 0, running: live ? { ...state.totals } : { X: 0, O: 0 }, done: false };
  const current = reveal;
  if (!live) {
    setStatus(`Revealing the ${state.category.label.toLowerCase()} of every pick...`);
    order.forEach(([mark, r], k) => {
      revealTimers.push(setTimeout(() => {
        const pick = state.picks[mark][r];
        current.lit = k + 1;
        current.running[mark] += pick.value;
        lightTile(state, k, pick, true);
        setTotal(mark, current.running[mark], state.category);
        sfx.playClockBeep();
      }, 400 + k * REVEAL_STEP));
    });
  } else {
    setStatus('Last pick in. Checking the totals...');
  }
  const wait = live ? 1200 : 400 + order.length * REVEAL_STEP + 500;
  revealTimers.push(setTimeout(() => {
    current.done = true;
    MARKS.forEach(mark => setTotal(mark, state.totals[mark], state.category));
    markWinner(state.winner);
    renderCard(state, names, false);
    sfx.playArenaBuzzer();
    if (state.winner !== 'draw') setTimeout(() => sfx.playWin(), 700);
    done();
  }, wait));
}

/** The final slip's text. */
export function finalText(state, names, mine = null) {
  const { X, O } = state.totals;
  const w = state.winner;
  const gap = Math.abs(X - O);
  let title;
  if (w === 'draw') title = 'Dead even';
  else if (mine) title = w === mine ? 'You win' : `${names[w]} wins`;
  else title = `${names[w]} wins`;
  const { label, unit } = state.category;
  const score = `<span class="x">${X.toLocaleString('en-US')}</span><span class="vs">${unit} to</span>` +
    `<span class="o">${O.toLocaleString('en-US')}</span>`;
  const average = (total) => {
    const each = total / state.slots.length;
    return `${each >= 1000 ? Math.round(each).toLocaleString('en-US') : each.toFixed(1)} ${unit}`;
  };
  const desc = w === 'draw'
    ? `The two rosters are level on ${label.toLowerCase()}.`
    : `${label}: ahead by ${gap.toLocaleString('en-US')} ${unit}. Average per player: ${names.X} ${average(X)}, ${names.O} ${average(O)}.`;
  return { title, score, desc, stamp: w === 'draw' ? 'draw' : w.toLowerCase() };
}
