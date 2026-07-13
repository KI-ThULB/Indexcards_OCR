import { useEffect, useRef, useCallback } from 'react';
import type { BatchProgress } from '../../store/wizardStore';
import { withWsToken } from '../../api/client';

export function useProcessingWebSocket(
  batchId: string | null,
  onMessage: (progress: BatchProgress) => void
) {
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  // Keep callback ref current — read only inside WS event handler, not during render
  useEffect(() => { onMessageRef.current = onMessage; });

  useEffect(() => {
    if (!batchId) return;

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = withWsToken(`${protocol}//${location.host}/api/v1/ws/task/${batchId}`);

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const data: BatchProgress = JSON.parse(event.data);
          onMessageRef.current(data);
        } catch {
          console.error('WS parse error', event.data);
        }
      };

      ws.onclose = () => {
        // Single reconnect after 1s; backend re-sends last state on reconnect
        setTimeout(() => {
          if (wsRef.current === ws) {
            connect();
          }
        }, 1000);
      };
    };

    connect();

    return () => {
      const ref = wsRef.current;
      wsRef.current = null; // prevent reconnect loop on cleanup
      if (ref) {
        if (ref.readyState === WebSocket.CONNECTING) {
          // Avoid "WebSocket is closed before connection is established" warning
          ref.onopen = () => ref.close();
        } else {
          ref.close();
        }
      }
    };
  }, [batchId]);

  const close = useCallback(() => {
    const ref = wsRef.current;
    wsRef.current = null;
    ref?.close();
  }, []);

  return { close };
}
