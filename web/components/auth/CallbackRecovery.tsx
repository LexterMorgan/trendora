"use client";

import Link from "next/link";

import { AuthNotice, AuthShell } from "@/components/auth/AuthShell";

/**
 * Shared recovery panel for invite and recovery links when either the session
 * lookup or the SDK URL verdict did not finish. It never presents the password
 * form and never labels the link invalid.
 */
export function CallbackRecovery({
  title,
  onRetry,
}: {
  title: string;
  onRetry: () => void;
}) {
  return (
    <AuthShell title={title}>
      <AuthNotice kind="error">
        We could not finish checking this link. This does not mean it is
        invalid.
      </AuthNotice>
      <p className="auth-lede">
        You can try the link check again, or return to sign in. A retry may
        still wait if the sign-in service does not respond.
      </p>
      <div className="auth-actions">
        <button
          type="button"
          className="primary-button"
          onClick={onRetry}
        >
          Retry link check
        </button>
        <Link className="secondary-button" href="/login">
          Go to sign in
        </Link>
      </div>
    </AuthShell>
  );
}
