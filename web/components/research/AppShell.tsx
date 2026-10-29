"use client";

import type { ReactNode } from "react";

import { ResearchShell, type ResearchView } from "@/components/research/ResearchShell";
import { useShellState } from "@/components/research/ShellStateProvider";

interface AppShellProps {
  view: ResearchView;
  section: string;
  children: ReactNode;
  motionEnabled?: boolean;
  onToggleMotion?: () => void;
  onNewResearch?: () => void;
  newResearchDisabled?: boolean;
  typingSignal?: number;
}

/**
 * Shared authenticated chrome for the main research surfaces. Theme and rail
 * state live in the layout-level provider; motion remains page-owned.
 */
export function AppShell({
  view,
  section,
  children,
  motionEnabled,
  onToggleMotion,
  onNewResearch,
  newResearchDisabled,
  typingSignal,
}: AppShellProps) {
  const { theme, toggleTheme } = useShellState();

  return (
    <ResearchShell
      view={view}
      section={section}
      theme={theme}
      onToggleTheme={toggleTheme}
      motionEnabled={motionEnabled}
      onToggleMotion={onToggleMotion}
      onNewResearch={onNewResearch}
      newResearchDisabled={newResearchDisabled}
      typingSignal={typingSignal}
    >
      {children}
    </ResearchShell>
  );
}
