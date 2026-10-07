"use client";

import { Fragment, useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { AuthShell, AuthNotice, AuthUnavailable } from "@/components/auth/AuthShell";
import { SignOutButton } from "@/components/SignOutButton";
import { gateDecision } from "@/lib/auth/session";
import { useSession } from "@/lib/auth/use-session";

/**
 * Gates children on the browser session.
 *
 * - loading / redirecting: neutral checking state, children never mount
 * - no config: availability notice, children never mount
 * - signed out: redirect to /login (no loop: /login fetches nothing)
 * - membership rejected: stable access-denied card, children unmount so no
 *   workspace content or in-flight request survives; no redirect, because a
 *   valid session bouncing through /login would loop
 * - signed in: children keyed on userId:epoch so an account switch or a
 *   forced sign-out (401) remounts content instead of leaving it stale
 */
export function Protected({ children }: { children: ReactNode }) {
  const router = useRouter();
  const session = useSession();
  const decision = gateDecision(session.status);

  useEffect(() => {
    if (decision === "login") router.replace("/login");
  }, [decision, router]);

  if (decision === "unavailable") return <AuthUnavailable />;

  if (decision !== "render") {
    return (
      <main className="auth-shell">
        <p className="loading-note" role="status">
          Checking your session…
        </p>
      </main>
    );
  }

  if (session.denied) {
    return (
      <AuthShell title="Access denied">
        <AuthNotice kind="error">{session.denied.message}</AuthNotice>
        <div className="auth-actions">
          <SignOutButton className="secondary-button" />
        </div>
      </AuthShell>
    );
  }

  return (
    <Fragment key={`${session.userId}:${session.epoch}`}>{children}</Fragment>
  );
}
