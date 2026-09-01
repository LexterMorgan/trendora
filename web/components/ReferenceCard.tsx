import type { ResearchReferenceResponse } from "@/lib/trendora-api";
import { formatDate, formatMetric, sourceLabel } from "@/lib/format";

interface ReferenceCardProps {
  reference: ResearchReferenceResponse;
}

export function ReferenceCard({ reference }: ReferenceCardProps) {
  const title = reference.title || "Untitled video";
  const url = reference.url ?? "#";

  return (
    <article className="reference-card">
      <div className="reference-card-top">
        <span className="source-badge">{sourceLabel(reference.source_code)}</span>
        {reference.channel_title && (
          <span className="reference-channel">{reference.channel_title}</span>
        )}
      </div>

      <h3 className="reference-title">{title}</h3>

      {reference.description && (
        <p className="reference-description">{reference.description}</p>
      )}

      <dl className="reference-metrics">
        <div className="metric">
          <dt>Views</dt>
          <dd>{formatMetric(reference.metrics.view_count)}</dd>
        </div>
        <div className="metric">
          <dt>Likes</dt>
          <dd>{formatMetric(reference.metrics.like_count)}</dd>
        </div>
        <div className="metric">
          <dt>Comments</dt>
          <dd>{formatMetric(reference.metrics.comment_count)}</dd>
        </div>
      </dl>

      <div className="reference-meta">
        <span>Published {formatDate(reference.published_at)}</span>
        <span>Source position #{reference.source_rank ?? "—"}</span>
      </div>

      <a
        className="view-original"
        href={url}
        target="_blank"
        rel="noopener noreferrer"
      >
        View original
      </a>
    </article>
  );
}
