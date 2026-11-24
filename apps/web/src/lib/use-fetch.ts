"use client";

import { useEffect, useRef, useState } from "react";

export interface FetchState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Minimal client-side loader. Reloads whenever `key` changes or `reload()` is called. */
export function useFetch<T>(
  key: string,
  load: () => Promise<T>,
): FetchState<T> {
  const [state, setState] = useState<{
    data: T | null;
    error: string | null;
    loading: boolean;
  }>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    let cancelled = false;
    loadRef.current().then(
      (data) => !cancelled && setState({ data, error: null, loading: false }),
      (e: unknown) =>
        !cancelled &&
        setState({
          data: null,
          error: e instanceof Error ? e.message : "Something went wrong",
          loading: false,
        }),
    );
    return () => {
      cancelled = true;
    };
  }, [key, tick]);

  return { ...state, reload: () => setTick((t) => t + 1) };
}
