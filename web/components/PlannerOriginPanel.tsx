"use client";

import { useEffect, useState } from "react";

import { getSessionStore } from "@/lib/auth/client";
import { getPlannerOrigin, type PlannerOrigin, type PlannerOriginSource } from "@/lib/planner-api";
import { ResearchApiError } from "@/lib/api";

const STATE_LABEL: Record<PlannerOriginSource["state"], string> = {
  available: "Source available",
  restricted: "Source hidden: report access required",
  expired: "Source retention window elapsed",
  unresolved: "Source time unknown",
};

/**
 * Read-only origin for an imported post: which report and item it came from,
 * the generated context, and the minimal source references with their state.
 * Never edits the post; a manually created post has no origin and this renders
 * nothing.
 */
export function PlannerOriginPanel({ postId }: { postId: string }) {
  const [origin, setOrigin] = useState<PlannerOrigin | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const binding = getSessionStore().getSessionBinding();
    getPlannerOrigin(postId, { signal: controller.signal })
      .then((value) => {
        if (!active) return;
        const now = getSessionStore().getSessionBinding();
        if (now.userId !== binding.userId || now.epoch !== binding.epoch) return;
        setOrigin(value);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof ResearchApiError && err.kind === "not_found") {
          setOrigin(null);
          return;
        }
        setError(err instanceof ResearchApiError ? err.message : "Origin unavailable.");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [postId]);

  if (error) {
    return <p className="drawer-muted planner-origin-error">{error}</p>;
  }
  if (!origin) return null;

  const context = origin.context ?? {};

  return (
    <details className="planner-origin report-secondary-details">
      <summary>Research origin</summary>
      <ul className="provenance-list">
        <li>Source report: {origin.report_id ?? "unknown"}</li>
        <li>
          Item: {origin.item_kind ?? "unknown"} #{origin.item_index ?? "?"}
          {origin.parent_idea_index !== null ? ` (parent idea #${origin.parent_idea_index})` : ""}
        </li>
        <li>Provenance: {origin.provenance}</li>
      </ul>
      {Object.keys(context).length > 0 && (
        <dl className="planner-origin-context">
          {Object.entries(context).map(([key, value]) => (
            <div key={key}>
              <dt>{key.replaceAll("_", " ")}</dt>
              <dd>{Array.isArray(value) ? value.join("\n") : String(value ?? "")}</dd>
            </div>
          ))}
        </dl>
      )}
      {origin.sources.length > 0 && (
        <>
          <h4 className="drawer-subheading">Sources</h4>
          <ul className="planner-origin-sources">
            {origin.sources.map((source) => (
              <li key={`${source.source_code}:${source.content_external_id}`}>
                <span>{source.source_code} · {source.content_external_id}</span>
                <span className="drawer-muted"> {STATE_LABEL[source.state]}</span>
                {source.url && source.state === "available" && (
                  <>
                    {" "}
                    <a href={source.url} target="_blank" rel="noopener noreferrer">
                      Open source
                    </a>
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </details>
  );
}
