"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { SignOutButton } from "@/components/SignOutButton";

export interface HeaderProps {
  /** Current view name, shown in the mobile menu (e.g. "Research Workspace"). */
  section: string;
  /** Optional action button rendered on the right. */
  actionLink?: { href: string; label: string };
}

// `match` lists every route prefix that belongs to a destination. A saved
// report (/report/[id]) belongs to Reports, so its nav item stays active.
const NAV = [
  { href: "/", label: "Research", match: ["/"] },
  { href: "/past-reports", label: "Reports", match: ["/past-reports", "/report"] },
  { href: "/planner", label: "Planner", match: ["/planner"] },
];

/**
 * App shell header. Primary destinations are always visible on desktop; on
 * narrow screens they collapse into a labelled Menu disclosure so no
 * destination depends on a hover or an unlabelled icon. The current
 * destination is marked with `aria-current`, not color alone.
 */
export function Header({ section, actionLink }: HeaderProps) {
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
          <span className="brand-icon" aria-hidden="true">
            T
          </span>
          <span className="brand-name">Trendora</span>
        </Link>
      </div>

      <nav className="header-nav" aria-label="Primary">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={isActive(item) ? "header-nav-link is-active" : "header-nav-link"}
            aria-current={isActive(item) ? "page" : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="header-action">
        {actionLink && (
          <Link href={actionLink.href} className="secondary-button header-action-link">
            {actionLink.label}
          </Link>
        )}
        <SignOutButton />
        <button
          type="button"
          className="menu-toggle"
          aria-expanded={menuOpen}
          aria-controls="header-mobile-menu"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className="menu-toggle-label">{menuOpen ? "Close" : "Menu"}</span>
          <span className="menu-toggle-icon" aria-hidden="true">
            {menuOpen ? "▲" : "▼"}
          </span>
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
