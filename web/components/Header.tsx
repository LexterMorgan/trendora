"use client";

import Link from "next/link";

export interface HeaderProps {
  /** Current view name, shown in the breadcrumb (e.g. "Research Workspace"). */
  section: string;
  /** Optional action button rendered on the right. */
  actionLink?: { href: string; label: string };
}

export function Header({ section, actionLink }: HeaderProps) {
  return (
    <header className="unified-header">
      <div className="header-brand">
        <Link href="/" className="brand-link" aria-label="Trendora home">
          <span className="brand-icon" aria-hidden="true">T</span>
          <span className="brand-name">Trendora</span>
        </Link>
      </div>

      <nav className="header-breadcrumb" aria-label="Breadcrumb">
        <Link href="/" className="breadcrumb-home">Home</Link>
        <span className="breadcrumb-separator" aria-hidden="true">·</span>
        <span className="breadcrumb-current" aria-current="page">
          {section}
        </span>
      </nav>

      {actionLink && (
        <div className="header-action">
          <Link href={actionLink.href} className="secondary-button">
            {actionLink.label}
          </Link>
        </div>
      )}
    </header>
  );
}
