import { useEffect, useRef, useState } from "react";

/** Polls `fetcher` every `intervalMs` and exposes the latest result.
 *
 * The dashboard uses polling rather than a websocket/SSE feed today — the
 * backend's realtime push layer (spec section 34) has not been built yet.
 * This hook is the seam where that would plug in: swap the setInterval body
 * for a subscription and the rest of the UI is unaffected.
 */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const result = await fetcherRef.current();
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err as Error);
      }
    };

    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs]);

  return { data, error };
}
