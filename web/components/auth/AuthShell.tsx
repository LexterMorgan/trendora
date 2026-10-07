"use client";

import type { ReactNode } from "react";

interface AuthShellProps {
  title: string;
  lede?: string;
  children: ReactNode;
}

/**
 * Centered paper card shared by /login, /accept-invite, /reset-password and
 * the session-gate states. Extends the existing Trendora identity: same
 * brand mark, palette, and field styles.
 */
export function AuthShell({ title, lede, children }: AuthShellProps) {
  return (
    <main className="auth-shell">
      <section className="auth-card" aria-labelledby="auth-title">
        <p className="brand">Trendora</p>
        <h1 className="auth-title" id="auth-title">
          {title}
        </h1>
        {lede && <p className="auth-lede">{lede}</p>}
        {children}
      </section>
    </main>
  );
}

/** Rendered whenever the Supabase env config is missing. */
export function AuthUnavailable() {
  return (
    <AuthShell title="Sign-in unavailable">
      <p className="auth-lede">
        This deployment doesn&apos;t have a sign-in service configured.
      </p>
      <p className="auth-note">
        Set the Supabase environment variables for this deployment to enable
        sign-in.
      </p>
    </AuthShell>
  );
}

export function AuthNotice({
  kind,
  children,
}: {
  kind: "error" | "ok";
  children: ReactNode;
}) {
  return (
    <p
      className={kind === "error" ? "auth-error" : "auth-ok"}
      role={kind === "error" ? "alert" : "status"}
    >
      {children}
    </p>
  );
}
