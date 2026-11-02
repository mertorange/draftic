// The WebSocket link to an online room: joining, reconnecting with the seat token, sending.

const RETRY_DELAYS_MS = [500, 1000, 2000, 4000, 8000];

// The seat token lives per tab: a reload gets the same seat back, while two tabs in one
// browser are two players.

function tokenKey(code) {
  return `draftic:room:${code}`;
}

function loadToken(code) {
  try {
    return sessionStorage.getItem(tokenKey(code));
  } catch (e) {
    return null;
  }
}

function saveToken(code, token) {
  try {
    sessionStorage.setItem(tokenKey(code), token);
  } catch (e) {}
}

function forgetToken(code) {
  try {
    sessionStorage.removeItem(tokenKey(code));
  } catch (e) {}
}

/** True when this tab already holds a seat in the room (a reload mid-game). */
export function hasSeat(code) {
  return Boolean(loadToken(code));
}

export class RoomConnection {
  /**
   * @param {string} code
   * @param {string} name
   * @param {{onRoom, onError, onStatus}} handlers
   *   onStatus receives 'connected' | 'reconnecting' | 'closed'
   */
  constructor(code, name, handlers) {
    this.code = code;
    this.name = name;
    this.handlers = handlers;
    this.welcomed = false;
    this.socket = null;
    this.attempt = 0;
    this.leaving = false;
    this.mark = null;
  }

  open() {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${scheme}://${location.host}/ws/rooms/${this.code}`);
    this.socket = socket;
    socket.addEventListener('open', () => {
      const token = loadToken(this.code);
      socket.send(JSON.stringify({ type: 'join', name: this.name, token }));
    });
    socket.addEventListener('message', (e) => this.receive(JSON.parse(e.data)));
    socket.addEventListener('close', () => {
      if (this.socket !== socket) return;
      if (this.leaving || this.attempt >= RETRY_DELAYS_MS.length) {
        this.handlers.onStatus('closed');
        return;
      }
      this.handlers.onStatus('reconnecting');
      setTimeout(() => this.open(), RETRY_DELAYS_MS[this.attempt++]);
    });
  }

  receive(msg) {
    if (msg.type === 'welcome') {
      this.attempt = 0;
      this.welcomed = true;
      this.mark = msg.mark;
      if (msg.token) saveToken(this.code, msg.token);
      this.handlers.onStatus('connected');
    } else if (msg.type === 'room') {
      this.handlers.onRoom(msg);
    } else if (msg.type === 'error') {
      if (!this.welcomed) this.leaving = true; // refused at the door (full room, bad code): don't retry
      this.handlers.onError(msg.reason);
    }
  }

  send(type, payload = {}) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type, ...payload }));
    }
  }

  leave() {
    this.leaving = true;
    this.send('leave');
    forgetToken(this.code);
    if (this.socket) this.socket.close();
  }
}
