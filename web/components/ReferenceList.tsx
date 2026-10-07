import type { ResearchReferenceResponse } from "@/lib/trendora-api";
import { ReferenceCard } from "./ReferenceCard";

interface ReferenceListProps {
  references: ResearchReferenceResponse[];
  window?: { date_from?: string; date_to?: string };
}

export function ReferenceList({ references, window }: ReferenceListProps) {
  return (
    <section className="reference-list" aria-label="Research references">
      <h2 className="section-title">References</h2>
      <div className="reference-grid">
        {references.map((reference) => (
          <ReferenceCard
            key={`${reference.source_code}-${reference.content_external_id}`}
            reference={reference}
            window={window}
          />
        ))}
      </div>
    </section>
  );
}
