// Minimal external store on React's useSyncExternalStore: `useStore(selector)`, `useStore.getState()`, `useStore.setState()`.
// Replaces Zustand: packages with wildcard `exports` ("./*") fail to resolve when the project path contains "*".
import { useSyncExternalStore } from 'react';

type Partialize<T> = Partial<T> | ((state: T) => Partial<T>);
export type SetState<T> = (partial: Partialize<T>) => void;
export type GetState<T> = () => T;

export function createStore<T extends object>(init: (set: SetState<T>, get: GetState<T>) => T) {
  let state: T;
  const listeners = new Set<() => void>();
  const get: GetState<T> = () => state;
  const set: SetState<T> = (partial) => {
    const next = typeof partial === 'function' ? partial(state) : partial;
    state = { ...state, ...next };
    listeners.forEach((l) => l());
  };
  state = init(set, get);
  const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };
  function useStore(): T;
  function useStore<U>(selector: (s: T) => U): U;
  function useStore<U>(selector: (s: T) => U = (s) => s as unknown as U): U {
    return useSyncExternalStore(subscribe, () => selector(state), () => selector(state));
  }
  useStore.getState = get;
  useStore.setState = set;
  useStore.subscribe = subscribe;
  return useStore;
}
