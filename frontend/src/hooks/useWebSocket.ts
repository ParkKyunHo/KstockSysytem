// React hook wrapper around :data:`wsClient`.
//
// ``useWsBootstrap`` should be mounted **once** at app top-level
// (after auth) -- it owns the singleton lifecycle.
//
// ``useWsChannels(['positions'])`` is the per-component subscriber.
// ``useWsMessages(handler)`` registers a listener bound to the
// component's lifetime.

import { useEffect } from 'react';

import { useAuth } from '@/contexts/AuthContext';
import {
  wsClient,
  type WsChannel,
  type WsEnvelope,
  type WsListener,
} from '@/lib/ws';

/**
 * Owns the global WS connection lifecycle. Mount once (e.g. inside
 * AppShell) so the connection follows auth state.
 */
export function useWsBootstrap(): void {
  const { isAuthenticated } = useAuth();
  useEffect(() => {
    if (!isAuthenticated) {
      wsClient.stop();
      return;
    }
    wsClient.start();
    return () => {
      // Do not stop when components remount -- AppShell unmounts only
      // on logout, which clears tokens and toggles isAuthenticated.
    };
  }, [isAuthenticated]);
}

/**
 * Subscribe to one or more channels for the lifetime of the component.
 */
export function useWsChannels(channels: WsChannel[]): void {
  useEffect(() => {
    if (channels.length === 0) return;
    wsClient.subscribe(channels);
    return () => {
      wsClient.unsubscribe(channels);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channels.join('|')]);
}

/**
 * Register a message listener.
 */
export function useWsMessages(handler: WsListener): void {
  useEffect(() => {
    const off = wsClient.on(handler);
    return () => {
      off();
    };
  }, [handler]);
}

export type { WsChannel, WsEnvelope };
