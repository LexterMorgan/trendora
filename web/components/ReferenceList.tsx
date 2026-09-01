import type { ResearchReferenceResponse } from "@/lib/trendora-api";
import { ReferenceCard } from "./ReferenceCard";

interface ReferenceListProps {
  references: ResearchReferenceResponse[];
}

export function ReferenceList({ references }: ReferenceListProps) {
  return (
    <section className="reference-list" aria-label="Research references">
      <h2 className="section-title">References</h2>
      <div className="reference-grid">
        {references.map((reference) => (
          <ReferenceCard
            key={`${reference.source_code}-${reference.content_external_id}`}
            reference={reference}
          />
        ))}
      </div>
    </section>
  );
}
