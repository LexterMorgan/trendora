"use client";

import { useEffect, useSyncExternalStore } from "react";

import { getSessionStore } from "./client.ts";
import type { SessionState } from "./session.ts";

const SERVER_SNAPSHOT: SessionState = {
  status: "loading",
  userId: null,
  epoch: 0,
  establishedToken: null,
  denied: null,
};

function subscribe(onStoreChange: () => void): () => void {
  return getSessionStore().subscribe(onStoreChange);
}

function getSnapshot(): SessionState {
  return getSessionStore().getSessionState();
}

function getServerSnapshot(): SessionState {
  return SERVER_SNAPSHOT;
}

/**
 * Subscribes a component to the shared session store. The store starts
 * listening to Supabase on mount (idempotent across components).
 */
export function useSession(): SessionState {
  const state = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  useEffect(() => {
    getSessionStore().start();
  }, []);
  return state;
}
