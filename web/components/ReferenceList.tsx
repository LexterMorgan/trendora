import type { ResearchReferenceResponse } from "@/lib/trendora-api";
import { ReferenceCard } from "./ReferenceCard";

interface ReferenceListProps {
  references: ResearchReferenceResponse[];
  window?: { date_from?: string; date_to?: string };
}

/** Cards shown before the library collapses the remainder behind a disclosure. */
const INITIAL_VISIBLE = 6;

/**
 * The source library. The first few cards show immediately; when there are
 * more, the rest stay behind one "Show all N sources" disclosure so the list
 * never opens as dozens of cards. The count stays visible either way.
 */
export function ReferenceList({ references, window }: ReferenceListProps) {
  const visible = references.slice(0, INITIAL_VISIBLE);
  const rest = references.slice(INITIAL_VISIBLE);
  const card = (reference: ResearchReferenceResponse) => (
    <ReferenceCard
      key={`${reference.source_code}-${reference.content_external_id}`}
      reference={reference}
      window={window}
    />
  );

  return (
    <section className="reference-list" aria-label="Research references">
      <h2 className="section-title">References</h2>
      <div className="reference-grid">{visible.map(card)}</div>
      {rest.length > 0 && (
        <details className="reference-more">
          <summary>Show all {references.length} sources</summary>
          <div className="reference-grid">{rest.map(card)}</div>
        </details>
      )}
    </section>
  );
}
