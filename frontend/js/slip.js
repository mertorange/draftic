// The player slip: the dialog where the team on the clock drafts someone. A pick always
// comes from the suggestions: the top one is chosen as soon as they show, Enter or Draft
// takes the chosen one, so a typo never costs a pick.
//
// In browse mode (eligible search) the whole list shows before anything is typed, best known
// first, with nothing chosen yet; typing narrows it to every name that matches.

import { matchNames } from './names.js';
import { $, closeModal, escapeHtml, isOpen, openModal } from './dom.js';

export class PlayerSlip {
  /**
   * @param {(id: number, name: string) => void} onSubmit
   * @param {() => void} onCancel
   */
  constructor(onSubmit, onCancel = () => {}) {
    this.onSubmit = onSubmit;
    this.onCancel = onCancel;
    this.modal = $('modal-select');
    this.input = $('search-player-input');
    this.list = $('search-results-list');
    this.confirm = $('btn-confirm-select');
    this.entries = null;    // the names to search, or null while they load
    this.minChars = 2;
    this.browse = false;    // show every name before anything is typed
    this.active = -1;
    this.options = [];

    // One set of listeners for the list, however long it gets
    const itemAt = (e) => e.target.closest('li[data-index]');
    this.list.addEventListener('mousedown', (e) => { if (itemAt(e)) e.preventDefault(); });
    this.list.addEventListener('click', (e) => {
      const li = itemAt(e);
      if (li) this.submit(this.options[Number(li.dataset.index)]);
    });
    this.list.addEventListener('mousemove', (e) => {
      const li = itemAt(e);
      if (li && Number(li.dataset.index) !== this.active) this.setActive(Number(li.dataset.index), false);
    });

    $('btn-cancel-select').addEventListener('click', () => this.cancel());
    this.confirm.addEventListener('click', () => this.submit(this.options[this.active]));
    this.input.addEventListener('input', () => this.onInput());
    this.input.addEventListener('keydown', (e) => this.onKeydown(e));
  }

  get isOpen() {
    return isOpen(this.modal);
  }

  /**
   * @param {{title, slot, criterion, hint, entries: Array|Promise<Array>, minChars, browse}} round
   */
  open({ title, slot, criterion, hint, entries, minChars = 2, browse = false }) {
    $('slip-title').textContent = title;
    $('req-slot').textContent = slot;
    $('req-crit').textContent = criterion;
    $('slip-hint').textContent = hint || '';
    this.minChars = minChars;
    this.browse = browse;
    this.input.value = '';
    this.input.placeholder = browse ? 'Type to narrow the list' : 'Start typing a name';
    this.render([], '');
    if (Array.isArray(entries)) {
      this.entries = entries;
      this.onInput();
    } else {
      this.entries = null;
      entries.then(list => {
        this.entries = list;
        if (this.isOpen) this.onInput();
      }).catch(() => {
        this.list.innerHTML = '<li class="none">Could not load the player names. Check the connection.</li>';
      });
    }
    openModal(this.modal);
    this.input.focus();
  }

  /** A new pool while the slip is open (online: the opponent's pick doesn't change it, but a reconnect may). */
  setEntries(entries) {
    this.entries = entries;
    if (this.isOpen) this.onInput();
  }

  close() {
    closeModal(this.modal);
  }

  cancel() {
    if (!this.isOpen) return;
    this.close();
    this.onCancel();
  }

  submit(option) {
    if (!option) return;
    this.close();
    this.onSubmit(option.id, option.name);
  }

  onInput() {
    const query = this.input.value.trim();
    if (this.browse && !query && this.entries) {
      this.render(everyone(this.entries), '');
      return;
    }
    if (query.length < this.minChars) {
      this.render([], '');
      return;
    }
    if (!this.entries) {
      this.list.innerHTML = '<li class="none">Loading the names...</li>';
      return;
    }
    this.render(matchNames(this.entries, query, this.browse ? Infinity : 8), query);
  }

  onKeydown(e) {
    const items = [...this.list.querySelectorAll('li[data-index]')];
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!items.length) return;
      e.preventDefault();
      const step = e.key === 'ArrowDown' ? 1 : -1;
      this.setActive((this.active + step + items.length) % items.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      this.submit(this.options[this.active]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      this.cancel();
    }
  }

  render(options, query) {
    this.active = -1;
    this.options = options;
    this.input.removeAttribute('aria-activedescendant');
    if (!query && !options.length) {
      this.list.innerHTML = '';
      this.input.setAttribute('aria-expanded', 'false');
      this.confirm.disabled = true;
      return;
    }
    if (!options.length) {
      this.list.innerHTML = '<li class="none">Nobody by that name here. Check the spelling.</li>';
    } else {
      this.list.innerHTML = options.map((option, i) =>
        `<li role="option" id="sugg-${i}" data-index="${i}" aria-selected="false">` +
        `<span>${highlight(option.name, query)}</span>${info(option)}</li>`
      ).join('');
      this.list.scrollTop = 0;
      // Typed: the top match is chosen. Browsing the whole list: nothing until it's pointed at
      if (query) this.setActive(0);
    }
    this.input.setAttribute('aria-expanded', 'true');
    this.confirm.disabled = this.active < 0;
  }

  /** scroll: bring the chosen one into view (keyboard), not when the mouse is on it already */
  setActive(index, scroll = true) {
    const items = this.list.querySelectorAll('li[data-index]');
    if (items[this.active]) items[this.active].setAttribute('aria-selected', 'false');
    this.active = index;
    this.confirm.disabled = index < 0;
    if (items[index]) {
      items[index].setAttribute('aria-selected', 'true');
      this.input.setAttribute('aria-activedescendant', items[index].id);
      if (scroll) items[index].scrollIntoView({ block: 'nearest' });
    }
  }
}

/** Every player once, in the list's order (the best known first), without other names. */
function everyone(entries) {
  const seen = new Set();
  return entries.filter(entry => !entry.aka && !seen.has(entry.id) && seen.add(entry.id));
}

/** The small box beside a name: the other name it matched, or the birth year of a namesake. */
function info({ aka, born }) {
  const parts = [];
  if (aka) parts.push(aka);
  if (born) parts.push(`b. ${String(born).slice(0, 4)}`);
  return parts.length ? `<span class="twin-info">${escapeHtml(parts.join(' · '))}</span>` : '';
}

function highlight(name, query) {
  const q = query.trim().toLowerCase();
  const i = name.toLowerCase().indexOf(q); // no highlight when accents or dots don't line up
  if (i < 0 || !q) return escapeHtml(name);
  return escapeHtml(name.slice(0, i)) + '<mark>' + escapeHtml(name.slice(i, i + q.length)) + '</mark>' +
    escapeHtml(name.slice(i + q.length));
}
