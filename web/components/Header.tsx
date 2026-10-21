"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { SignOutButton } from "@/components/SignOutButton";
import { Brand } from "@/components/Brand";

export interface HeaderProps {
  /** Current view name, shown in the mobile menu (e.g. "Research Workspace"). */
  section: string;
}

// `match` lists every route prefix that belongs to a destination. A saved
// report (/report/[id]) belongs to Reports, so its nav item stays active.
const NAV = [
  { href: "/", label: "Research", match: ["/"], icon: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm5 12 6 6" },
  { href: "/past-reports", label: "Reports", match: ["/past-reports", "/report"], icon: "M6 3h9l4 4v14H6V3Zm8 0v5h5M9 12h7M9 16h7" },
  { href: "/discover", label: "Discover", match: ["/discover"], icon: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm3 6-2 5-5 2 2-5 5-2Z" },
  { href: "/planner", label: "Planner", match: ["/planner"], icon: "M4 5h16v16H4V5Zm0 5h16M8 2v6M16 2v6" },
];

/**
 * App shell header. Primary destinations are always visible on desktop; on
 * narrow screens they collapse into a labelled Menu disclosure so no
 * destination depends on a hover or an unlabelled icon. The current
 * destination is marked with `aria-current`, not color alone. Contextual
 * actions live on the page that owns them, so the header never repeats a
 * destination as a second button.
 */
export function Header({ section }: HeaderProps) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  const isActive = (item: (typeof NAV)[number]) =>
    item.match.some((prefix) =>
      prefix === "/" ? pathname === "/" : pathname === prefix || pathname.startsWith(`${prefix}/`),
    );

  return (
    <header className="unified-header">
      <div className="header-brand">
        <Link href="/" className="brand-link" aria-label="Trendora home">
          <Brand />
        </Link>
        <span className="alpha-label">Alpha v0.1</span>
      </div>

      <nav className="header-nav" aria-label="Primary">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={isActive(item) ? "header-nav-link is-active" : "header-nav-link"}
            aria-current={isActive(item) ? "page" : undefined}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d={item.icon} /></svg>
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="header-action">
        <SignOutButton />
        <button
          type="button"
          className="menu-toggle"
          aria-expanded={menuOpen}
          aria-controls="header-mobile-menu"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className="menu-toggle-label">{menuOpen ? "Close" : "Menu"}</span>
          <svg className="menu-toggle-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            {menuOpen ? <path d="m5 5 10 10M15 5 5 15" /> : <path d="M3 6h14M3 10h14M3 14h14" />}
          </svg>
        </button>
      </div>

      {menuOpen && (
        <div className="header-mobile-menu" id="header-mobile-menu">
          <p className="header-mobile-section">{section}</p>
          <nav className="header-mobile-nav" aria-label="Primary mobile">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={isActive(item) ? "header-mobile-link is-active" : "header-mobile-link"}
                aria-current={isActive(item) ? "page" : undefined}
                onClick={() => setMenuOpen(false)}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      )}
    </header>
  );
}
