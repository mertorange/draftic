// The game server's HTTP API.

async function request(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = '';
    try {
      detail = (await res.json()).detail || '';
    } catch (e) {}
    throw Object.assign(new Error(detail || `${options.method || 'GET'} ${path} failed with ${res.status}`),
      { status: res.status, detail });
  }
  return res.json();
}

function post(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
}

export const api = {
  newDraft: (settings) => post('/api/drafts', settings),
  pick: (draftId, mark, id) => post(`/api/drafts/${draftId}/pick`, { mark, id }),
  shotClock: (draftId, mark) => post(`/api/drafts/${draftId}/shot-clock`, { mark }),
  leagues: () => request('/api/leagues'),
  players: (league) => request(`/api/players?league=${encodeURIComponent(league)}`),
  createRoom: (settings) => post('/api/rooms', settings),
  roomInfo: (code) => request(`/api/rooms/${encodeURIComponent(code)}`)
};
