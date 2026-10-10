"use client";

import { useEffect, useRef } from "react";

import type { ResolvedCitation, ChainLink } from "@/lib/report-provenance";

interface CitationDrawerProps {
  open: boolean;
  title: string;
  targetLabel: string;
  citations: ResolvedCitation[];
  chain: ChainLink[];
  onClose: () => void;
}

export function CitationDrawer({
  open,
  title,
  targetLabel,
  citations,
  chain,
  onClose,
}: CitationDrawerProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  // Native <dialog>.showModal() makes the rest of the page inert and moves
  // focus to the first focusable control (Close). Escape is intercepted via
  // onCancel so React state stays the source of truth; closing restores focus
  // to the control that opened the drawer. A keydown handler cycles Tab and
  // Shift+Tab among the drawer's focusable controls, so focus cannot leave the
  // modal even where the browser's own dialog wrapping is unreliable.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || !dialog || dialog.open) return;
    const returnFocus = document.activeElement as HTMLElement | null;
    dialog.showModal();

    function focusable(): HTMLElement[] {
      return Array.from(
        dialog!.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.getClientRects().length > 0);
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const items = focusable();
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (event.shiftKey) {
        if (active === first || !active || !dialog!.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last || !active || !dialog!.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    }

    dialog.addEventListener("keydown", onKeyDown);
    return () => {
      dialog.removeEventListener("keydown", onKeyDown);
      if (dialog.open) dialog.close();
      returnFocus?.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      className="drawer-dialog"
      aria-label="Citation trace"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        // Backdrop clicks target the dialog element itself.
        if (event.target === dialogRef.current) onClose();
      }}
    >
      <div className="drawer">
        <div className="drawer-header">
          <h3 className="section-title">Citation trace</h3>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            aria-label="Close citation trace"
          >
            ✕
          </button>
        </div>

        <p className="drawer-target">
          <strong>{targetLabel}</strong>: {title}
        </p>

        <h4 className="drawer-subheading">Upstream chain</h4>
        {chain.length === 0 ? (
          <p className="drawer-muted">No upstream chain available in this response.</p>
        ) : (
          <ol className="chain-list">
            {chain.map((link, index) => (
              <li key={index} className={link.resolved ? "" : "chain-unresolved"}>
                <span className="chain-label">{link.label}</span>
                <span className="chain-value">
                  {link.value}
                  {!link.resolved && " (Unresolved provenance)"}
                </span>
              </li>
            ))}
          </ol>
        )}

        <h4 className="drawer-subheading">Citations</h4>
        <ul className="citation-list">
          {citations.map((citation, index) => (
            <li key={index} className={citation.resolved ? "" : "citation-unresolved"}>
              <span className="chain-label">{citation.kind}</span>
              <span className="chain-value">{citation.detail}</span>

              {citation.references.length > 0 && (
                <ul className="reference-trace-list">
                  {citation.references.map((entry, refIndex) => (
                    <li key={refIndex} className="reference-trace">
                      <span className="chain-value">
                        {entry.source}:{entry.referenceId.content_external_id}
                      </span>
                      {entry.title && <span className="drawer-muted">{entry.title}</span>}
                      {entry.url ? (
                        <a
                          className="view-original"
                          href={entry.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          View original
                        </a>
                      ) : (
                        <span className="chain-unresolved">No original URL</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}

              {citation.unresolvedIdentifiers.length > 0 && (
                <span className="chain-unresolved">
                  Unresolved provenance: {citation.unresolvedIdentifiers.join(", ")}
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </dialog>
  );
}
