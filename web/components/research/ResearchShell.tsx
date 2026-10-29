"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { SignOutButton } from "@/components/SignOutButton";
import { JellyfishOcean, type OceanTheme } from "@/components/research/JellyfishOcean";
import { useShellState } from "@/components/research/ShellStateProvider";

export type ResearchView =
  | "home"
  | "setup"
  | "results"
  | "reports"
  | "planner"
  | "discover"
  | "report";

interface ResearchShellProps {
  view: ResearchView;
  section: string;
  theme: OceanTheme;
  onToggleTheme: () => void;
  motionEnabled?: boolean;
  onToggleMotion?: () => void;
  onNewResearch?: () => void;
  newResearchDisabled?: boolean;
  typingSignal?: number;
  children: ReactNode;
}

function Icon({ name, className = "" }: { name: string; className?: string }) {
  const paths: Record<string, ReactNode> = {
    pen: <><path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.4 2.6a1 1 0 0 1 3 3l-9 9a2 2 0 0 1-.9.5l-2.9.8a.5.5 0 0 1-.6-.6l.8-2.9a2 2 0 0 1 .5-.9z" /></>,
    reports: <><path d="M6 3h9l4 4v14H6V3Z" /><path d="M14 3v5h5M9 12h7M9 16h7" /></>,
    calendar: <><path d="M4 5h16v16H4V5Zm0 5h16M8 2v6M16 2v6" /></>,
    compass: <><circle cx="12" cy="12" r="9" /><path d="m16 8-2.3 6.7L8 17l2.3-6.7L16 8Z" /></>,
    history: <><path d="M3 12a9 9 0 1 0 9-9 9.8 9.8 0 0 0-6.7 2.7L3 8" /><path d="M3 3v5h5M12 7v5l4 2" /></>,
    pause: <><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" /></>,
    play: <path d="M6 3l14 9-14 9z" />,
    panel: <><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 3v18" /></>,
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
    moon: <path d="M20.4 14.4A8.5 8.5 0 0 1 9.6 3.6 8.5 8.5 0 1 0 20.4 14.4Z" />,
    menu: <><path d="M4 7h16M4 12h16M4 17h10" /></>,
    close: <><path d="m5 5 14 14M19 5 5 19" /></>,
    arrow: <><path d="M7 7h10v10" /><path d="M7 17 17 7" /></>,
  };
  return (
    <svg className={`research-icon ${className}`.trim()} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name] ?? paths.reports}
    </svg>
  );
}

export function ResearchShell({
  view,
  section,
  theme,
  onToggleTheme,
  motionEnabled = false,
  onToggleMotion,
  onNewResearch,
  newResearchDisabled = false,
  typingSignal = 0,
  children,
}: ResearchShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { collapsed, toggleCollapsed } = useShellState();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const railRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const firstNavRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 48rem)");
    const sync = () => {
      setIsMobile(query.matches);
      if (!query.matches) setDrawerOpen(false);
    };
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    const inert = isMobile && !drawerOpen;
    (rail as HTMLElement & { inert: boolean }).inert = inert;
    if (inert) rail.setAttribute("aria-hidden", "true");
    else rail.removeAttribute("aria-hidden");
  }, [isMobile, drawerOpen]);

  useEffect(() => {
    if (!drawerOpen) return;
    const frame = requestAnimationFrame(() => firstNavRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [drawerOpen]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setDrawerOpen(false);
        requestAnimationFrame(() => menuRef.current?.focus());
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  function closeDrawer() {
    setDrawerOpen(false);
  }

  function handleDrawerKeyDown(event: React.KeyboardEvent<HTMLElement>) {
    if (!drawerOpen || !isMobile || event.key !== "Tab") return;
    const rail = railRef.current;
    if (!rail) return;
    const focusable = Array.from(
      rail.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'),
    ).filter((element) => element.getClientRects().length > 0);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function handleNewResearch() {
    closeDrawer();
    if (onNewResearch) onNewResearch();
    else router.push("/");
  }

  const isReports = pathname === "/past-reports" || pathname.startsWith("/report/");
  const isPlanner = pathname === "/planner" || pathname.startsWith("/planner/");
  const isDiscover = pathname === "/discover";
  const isResearch = pathname === "/";

  return (
    <div
      className={`research-shell ${collapsed ? "is-collapsed" : "is-expanded"} ${drawerOpen ? "is-drawer-open" : ""} ${theme === "light" ? "is-light" : ""}`.trim()}
      data-rail={collapsed ? "collapsed" : "expanded"}
      data-drawer={drawerOpen ? "open" : "closed"}
      data-theme={theme}
      data-view={view}
    >
      <aside
        className="research-rail"
        id="research-rail"
        ref={railRef}
        aria-label="Workspace"
        onKeyDown={handleDrawerKeyDown}
      >
        <button className="research-brand" type="button" onClick={handleNewResearch} aria-label="Trendora home">
          <Image className="research-brand-mark" src="/brand/mark.svg" alt="" width={28} height={28} priority />
          <span className="research-wordmark">trendora</span>
        </button>

        <nav className="research-nav" aria-label="Primary">
          <button
            ref={firstNavRef}
            type="button"
            className="research-nav-item"
            aria-current={isResearch ? "page" : undefined}
            onClick={handleNewResearch}
            disabled={newResearchDisabled}
          >
            <Icon name="pen" />
            <span className="research-nav-label">New research</span>
          </button>
          <Link
            href="/past-reports"
            className="research-nav-item"
            aria-current={isReports ? "page" : undefined}
            onClick={closeDrawer}
          >
            <Icon name="reports" />
            <span className="research-nav-label">Reports</span>
          </Link>
          <Link
            href="/planner"
            className="research-nav-item"
            aria-current={isPlanner ? "page" : undefined}
            onClick={closeDrawer}
          >
            <Icon name="calendar" />
            <span className="research-nav-label">Planner</span>
          </Link>
          <Link
            href="/discover"
            className="research-nav-item"
            aria-current={isDiscover ? "page" : undefined}
            onClick={closeDrawer}
          >
            <Icon name="compass" />
            <span className="research-nav-label">Explore sources</span>
          </Link>
        </nav>

        <div className="research-rail-foot">
          {view === "home" && onToggleMotion && (
            <button type="button" className="research-nav-item" onClick={onToggleMotion} aria-label={motionEnabled ? "Pause motion" : "Resume motion"}>
              <Icon name={motionEnabled ? "pause" : "play"} />
              <span className="research-nav-label">{motionEnabled ? "Pause motion" : "Resume motion"}</span>
            </button>
          )}
          <SignOutButton className="research-signout" />
        </div>
      </aside>

      {drawerOpen && <div className="research-scrim" aria-hidden="true" onClick={closeDrawer} />}

      <div className="research-main-column">
        {view === "home" && <JellyfishOcean playing={motionEnabled} typingSignal={typingSignal} theme={theme} />}
        <header className="research-topbar">
          <button
            type="button"
            className="research-sidebar-toggle"
            aria-expanded={!collapsed}
            aria-controls="research-rail"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={toggleCollapsed}
          >
            <Icon name="panel" />
          </button>
          <button
            ref={menuRef}
            type="button"
            className="research-menu-button"
            aria-expanded={drawerOpen}
            aria-controls="research-rail"
            aria-label={drawerOpen ? "Close menu" : "Open menu"}
            onClick={() => setDrawerOpen((open) => !open)}
          >
            <Icon name={drawerOpen ? "close" : "menu"} />
          </button>
          <div className="research-topbar-actions">
            <button
              type="button"
              className="research-theme-toggle"
              aria-label={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
              aria-pressed={theme === "light"}
              onClick={onToggleTheme}
            >
              <Icon name={theme === "light" ? "moon" : "sun"} />
            </button>
            <Link className="research-history-link" href="/past-reports">
              <Icon name="history" />
              <span>History</span>
            </Link>
          </div>
        </header>
        <main className="workspace research-main" id="main" aria-label={section}>
          {children}
        </main>
      </div>
    </div>
  );
}
