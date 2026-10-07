import type { ResearchReferenceResponse } from "@/lib/trendora-api";
import { formatDate, formatMetric, sourceLabel } from "@/lib/format";
import { publicationDay, publicationScope, publicationScopeLabel } from "@/lib/report-provenance";

interface ReferenceCardProps {
  reference: ResearchReferenceResponse;
  window?: { date_from?: string; date_to?: string };
}

export function ReferenceCard({ reference, window }: ReferenceCardProps) {
  const isFacebook = reference.source_code === "facebook";
  const isYouTube = reference.source_code === "youtube";
  const title = reference.title || (isFacebook ? "Facebook post" : isYouTube ? "Untitled video" : "Untitled source");
  const published = publicationDay(reference.published_at) ? formatDate(reference.published_at) : "—";
  const collected = formatDate(reference.collected_at);
  const metric = (value: number | null | undefined) => value == null ? "Unknown" : formatMetric(value);

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

      {(isFacebook || isYouTube) && <dl className="reference-metrics">
        {isFacebook ? (
          <>
            <div className="metric">
              <dt>Reactions</dt>
              <dd>{metric(reference.metrics?.reaction_count)}</dd>
            </div>
            <div className="metric">
              <dt>Comments</dt>
              <dd>{metric(reference.metrics?.comment_count)}</dd>
            </div>
            <div className="metric">
              <dt>Shares</dt>
              <dd>{metric(reference.metrics?.share_count)}</dd>
            </div>
          </>
        ) : (
          <>
            <div className="metric">
              <dt>Views</dt>
              <dd>{metric(reference.metrics?.view_count)}</dd>
            </div>
            <div className="metric">
              <dt>Likes</dt>
              <dd>{metric(reference.metrics?.like_count)}</dd>
            </div>
            <div className="metric">
              <dt>Comments</dt>
              <dd>{metric(reference.metrics?.comment_count)}</dd>
            </div>
          </>
        )}
      </dl>}
      {(isFacebook || isYouTube) && (
        <p className="drawer-muted">Counts observed at collection, not a measure of growth. Missing values are unknown.</p>
      )}

      <div className="reference-meta">
        <span>{published === "—" ? "Publication date unknown" : <>Published <time dateTime={reference.published_at ?? undefined}>{published}</time></>}</span>
        <span>{collected === "—" ? "Collection date unknown" : <>Collected <time dateTime={reference.collected_at}>{collected}</time></>}</span>
        {(reference.market_contexts?.length ?? 0) > 0 && (
          <span title="Regional YouTube availability/viewability — not creator nationality, content origin, or language">
            Available in {reference.market_contexts.join(" · ")}
          </span>
        )}
        <span>Source position: {reference.source_rank ?? "Unknown"}</span>
      </div>

      <p className="drawer-muted" data-publication-scope={publicationScope(reference.published_at, window)}>
        {publicationScopeLabel(publicationScope(reference.published_at, window))}. Event date unavailable;
        publication timing does not verify when a development happened.
      </p>

      {reference.source_code === "public_web" && (
        <p className="drawer-muted">Timeframe coverage is unverified for this public-web result.</p>
      )}

      {reference.url ? <a
        className="view-original"
        href={reference.url}
        target="_blank"
        rel="noopener noreferrer"
      >
        View original
      </a> : <span className="drawer-muted">Original URL unavailable.</span>}
    </article>
  );
}
