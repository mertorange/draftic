// Name lists for the autocomplete, filtered right here as the player types. Eligible search
// gets the round's pool with every draft update; extreme search fetches the whole league
// once. Both hold names only: nothing that gives a height away.

import { api } from './api.js';

const loading = {};   // league -> promise of the entries
const loaded = {};    // league -> entries, once they are here

// Letters that don't split into a base letter and an accent
const PLAIN = { 'ı': 'i', 'İ': 'i', 'ø': 'o', 'Ø': 'o', 'đ': 'd', 'Đ': 'd', 'ł': 'l', 'Ł': 'l', 'ß': 'ss', 'æ': 'ae' };

/** Lower case without accents or punctuation: 'Dončić' finds Doncic, 'cj mccollum' C.J. McCollum. */
export function fold(text) {
  return text.replace(/[ıİøØđĐłŁßæ]/g, ch => PLAIN[ch])
    .normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[.,'’"]/g, '').replace(/-/g, ' ');
}

/** Search entries for a list of {id, name, born?, aka?}; each other name is an entry of its own. */
export function makeEntries(players) {
  const entries = [];
  for (const p of players) {
    entries.push({ id: p.id, name: p.name, born: p.born || null, folded: fold(p.name), rank: entries.length });
    for (const aka of p.aka || []) {
      entries.push({ id: p.id, name: p.name, born: p.born || null, folded: fold(aka), aka, rank: entries.length });
    }
  }
  return entries;
}

/** Every player in the league (extreme search), fetched once per league. */
export function loadLeague(league) {
  if (!loading[league]) {
    loading[league] = api.players(league)
      .then(({ players }) => (loaded[league] = makeEntries(players)))
      .catch(err => {
        delete loading[league]; // try again next time
        throw err;
      });
  }
  return loading[league];
}

/**
 * Suggestions for what has been typed: a word of the name starting with it first, then the
 * name containing it anywhere; ties keep the list's order. One suggestion per player.
 */
export function matchNames(entries, query, limit = 8) {
  const q = fold(query.trim());
  if (!q) return [];
  const scored = [];
  for (const entry of entries) {
    const at = entry.folded.indexOf(q);
    if (at < 0) continue;
    const score = at === 0 ? 0 : entry.folded[at - 1] === ' ' ? 1 : 2;
    scored.push([score, entry]);
  }
  scored.sort((a, b) => a[0] - b[0] || a[1].rank - b[1].rank);
  const seen = new Set();
  const options = [];
  for (const [, entry] of scored) {
    if (seen.has(entry.id)) continue;
    seen.add(entry.id);
    options.push(entry);
    if (options.length >= limit) break;
  }
  return options;
}
