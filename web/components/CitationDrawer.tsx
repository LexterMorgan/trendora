"use client";

import { useEffect } from "react";

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
  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="drawer-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Citation trace"
      onClick={onClose}
    >
      <div className="drawer" onClick={(event) => event.stopPropagation()}>
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
    </div>
  );
}
