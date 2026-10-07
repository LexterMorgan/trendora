"use client";

import { useState } from "react";

import { getSessionStore } from "@/lib/auth/client";

/**
 * Visible sign-out control for every authenticated view. Clearing the local
 * session flips the shared store to signedOut, so `Protected` redirects to
 * /login on its own.
 */
export function SignOutButton({ className = "secondary-button" }: { className?: string }) {
  const [pending, setPending] = useState(false);

  return (
    <button
      type="button"
      className={`${className} sign-out-button`}
      disabled={pending}
      onClick={() => {
        setPending(true);
        void getSessionStore()
          .signOut()
          .finally(() => setPending(false));
      }}
    >
      Sign out
    </button>
  );
}
