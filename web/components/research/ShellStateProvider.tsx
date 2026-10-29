"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

import type { OceanTheme } from "@/components/research/JellyfishOcean";

interface ShellState {
  theme: OceanTheme;
  collapsed: boolean;
  toggleTheme: () => void;
  toggleCollapsed: () => void;
}

const ShellStateContext = createContext<ShellState | null>(null);

function readTheme(): OceanTheme {
  if (typeof window === "undefined") return "dark";
  try {
    return window.localStorage.getItem("trendora:research-theme") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function readCollapsed(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem("trendora:research-rail") !== "expanded";
  } catch {
    return true;
  }
}

/**
 * Layout-level state for the one shared shell. This renders no chrome, so it
 * is safe on auth and report-detail routes as well.
 */
export function ShellStateProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<OceanTheme>(readTheme);
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed);

  function toggleTheme() {
    setTheme((current) => {
      const next: OceanTheme = current === "dark" ? "light" : "dark";
      try {
        localStorage.setItem("trendora:research-theme", next);
      } catch {
        // The control still works when storage is unavailable.
      }
      return next;
    });
  }

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;
      try {
        localStorage.setItem("trendora:research-rail", next ? "collapsed" : "expanded");
      } catch {
        // The visual state still updates without persistence.
      }
      return next;
    });
  }

  return (
    <ShellStateContext.Provider value={{ theme, collapsed, toggleTheme, toggleCollapsed }}>
      {children}
    </ShellStateContext.Provider>
  );
}

export function useShellState(): ShellState {
  const state = useContext(ShellStateContext);
  if (!state) throw new Error("useShellState must be used inside ShellStateProvider");
  return state;
}
