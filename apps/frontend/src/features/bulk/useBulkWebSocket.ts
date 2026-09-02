import { useEffect, useRef } from 'react';
import type { BulkProgress } from '../../api/bulkApi';
import { withWsToken } from '../../api/client';

/**
 * Subscribe to a bulk run's live progress.
 *
 * Mirrors useProcessingWebSocket, on channel `bulk:<bulkRunId>` of the same
 * endpoint. The backend re-sends the last known state on connect, so a browser
 * close, reload or dropped connection re-attaches to a running job rather than
 * losing it.
 */
export function useBulkWebSocket(
  bulkRunId: string | null,
  onMessage: (progress: BulkProgress) => void
) {
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  // Keep the callback ref current — read only inside the WS handler, not during render.
  useEffect(() => {
    onMessageRef.current = onMessage;
  });

  useEffect(() => {
    if (!bulkRunId) return;

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = withWsToken(
      `${protocol}//${location.host}/api/v1/ws/task/bulk:${bulkRunId}`
    );

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          onMessageRef.current(JSON.parse(event.data) as BulkProgress);
        } catch {
          console.error('Bulk WS parse error', event.data);
        }
      };

      ws.onclose = () => {
        // A bulk run can last hours, so keep retrying rather than giving up
        // after one attempt; the backend replays the last state on reconnect.
        setTimeout(() => {
          if (wsRef.current === ws) connect();
        }, 2000);
      };
    };

    connect();

    return () => {
      const ref = wsRef.current;
      wsRef.current = null; // prevent the reconnect loop from firing on cleanup
      if (ref) {
        if (ref.readyState === WebSocket.CONNECTING) {
          ref.onopen = () => ref.close();
        } else {
          ref.close();
        }
      }
    };
  }, [bulkRunId]);
}
