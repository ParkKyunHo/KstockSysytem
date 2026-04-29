// V7.1 WebSocket client (09_API_SPEC §11).
//
// * Auth via ``?token=`` query string (PRD §11.1 -- browser cannot set
//   Authorization headers on WebSocket).
// * PING every 30s, server replies PONG.
// * Reconnection with exponential backoff 1→2→4→8→16→30s (PRD §11.5).
// * Channel subscription state survives reconnects -- subscriptions are
//   re-sent on every connect.

import { tokenStore } from './tokenStore';

export type WsChannel =
  | 'positions'
  | 'boxes'
  | 'notifications'
  | 'system'
  | 'tracked_stocks';

export interface WsEnvelope {
  type: string;
  channel?: WsChannel;
  data?: Record<string, unknown>;
  session_id?: string;
  server_time?: string;
  channels?: WsChannel[];
  message?: string;
}

export type WsListener = (env: WsEnvelope) => void;

interface ClientState {
  socket: WebSocket | null;
  pingTimer: number | null;
  reconnectTimer: number | null;
  attempts: number;
  destroyed: boolean;
  desiredChannels: Set<WsChannel>;
  listeners: Set<WsListener>;
  connected: boolean;
}

function buildUrl(): string {
  // F2 (2026-04-29): JWT는 ``Sec-WebSocket-Protocol`` 헤더로 전달하므로
  // URL에 ``?token=`` 를 더 이상 넣지 않는다. uvicorn access log
  // (journalctl) 에 토큰이 평문으로 남지 않게 하기 위함. 서버는 헤더의
  // 첫 protocol 을 token 으로 인식한다.
  const base = import.meta.env.VITE_WS_BASE_URL as string | undefined;
  const wsBase =
    base ??
    (() => {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${proto}//${window.location.host}`;
    })();
  return `${wsBase}/api/v71/ws`;
}

const BACKOFF_SECONDS = [1, 2, 4, 8, 16, 30];

function backoffSeconds(attempt: number): number {
  return BACKOFF_SECONDS[Math.min(attempt, BACKOFF_SECONDS.length - 1)];
}

class WsClient {
  private state: ClientState = {
    socket: null,
    pingTimer: null,
    reconnectTimer: null,
    attempts: 0,
    destroyed: false,
    desiredChannels: new Set<WsChannel>(),
    listeners: new Set<WsListener>(),
    connected: false,
  };

  isConnected(): boolean {
    return this.state.connected;
  }

  on(listener: WsListener): () => void {
    this.state.listeners.add(listener);
    return () => {
      this.state.listeners.delete(listener);
    };
  }

  subscribe(channels: WsChannel[]): void {
    channels.forEach((c) => this.state.desiredChannels.add(c));
    if (this.state.connected) {
      this.send({ type: 'SUBSCRIBE', channels });
    }
  }

  unsubscribe(channels: WsChannel[]): void {
    channels.forEach((c) => this.state.desiredChannels.delete(c));
    if (this.state.connected) {
      this.send({ type: 'UNSUBSCRIBE', channels });
    }
  }

  /** Connect / reconnect. Idempotent. */
  start(): void {
    if (this.state.destroyed) return;
    if (this.state.socket && this.state.socket.readyState <= 1) return;
    const token = tokenStore.getAccessToken();
    // F2: token 을 Sec-WebSocket-Protocol 헤더의 첫 protocol 로 전달.
    // 서버는 이를 echo back 하며, 토큰이 access log URL 에 노출되지 않는다.
    // 토큰이 없으면 connection 자체를 시도하지 않고 close 상태 유지
    // (서버 측에서 1008 로 거절될 것).
    const ws = token
      ? new WebSocket(buildUrl(), [token])
      : new WebSocket(buildUrl());
    this.state.socket = ws;

    ws.addEventListener('open', () => this.handleOpen());
    ws.addEventListener('message', (e) => this.handleMessage(e));
    ws.addEventListener('close', (e) => this.handleClose(e));
    ws.addEventListener('error', () => {
      // ``close`` will fire next; the close handler manages reconnect.
    });
  }

  /** Permanent stop (logout / unmount). */
  stop(): void {
    this.state.destroyed = true;
    this.clearTimers();
    if (this.state.socket) {
      try {
        this.state.socket.close(1000, 'client_stop');
      } catch {
        // ignore
      }
      this.state.socket = null;
    }
    this.state.connected = false;
  }

  private handleOpen(): void {
    this.state.attempts = 0;
    this.state.connected = true;
    // Re-subscribe to whatever channels the caller wanted.
    if (this.state.desiredChannels.size > 0) {
      this.send({
        type: 'SUBSCRIBE',
        channels: Array.from(this.state.desiredChannels),
      });
    }
    this.startPing();
  }

  private handleMessage(event: MessageEvent): void {
    let payload: WsEnvelope;
    try {
      payload = JSON.parse(event.data as string) as WsEnvelope;
    } catch {
      return;
    }
    this.state.listeners.forEach((l) => {
      try {
        l(payload);
      } catch {
        // listener errors are swallowed -- WS pipeline must keep flowing
      }
    });
  }

  private handleClose(_event: CloseEvent): void {
    this.state.connected = false;
    this.clearTimers();
    if (this.state.destroyed) return;
    const seconds = backoffSeconds(this.state.attempts);
    this.state.attempts += 1;
    this.state.reconnectTimer = window.setTimeout(
      () => this.start(),
      seconds * 1000,
    );
  }

  private startPing(): void {
    if (this.state.pingTimer != null) return;
    this.state.pingTimer = window.setInterval(() => {
      if (this.state.socket?.readyState === WebSocket.OPEN) {
        this.send({ type: 'PING' });
      }
    }, 30_000);
  }

  private clearTimers(): void {
    if (this.state.pingTimer != null) {
      window.clearInterval(this.state.pingTimer);
      this.state.pingTimer = null;
    }
    if (this.state.reconnectTimer != null) {
      window.clearTimeout(this.state.reconnectTimer);
      this.state.reconnectTimer = null;
    }
  }

  private send(payload: Record<string, unknown>): void {
    if (this.state.socket?.readyState === WebSocket.OPEN) {
      this.state.socket.send(JSON.stringify(payload));
    }
  }
}

export const wsClient = new WsClient();
