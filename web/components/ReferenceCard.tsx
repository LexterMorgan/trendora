"use client";

import { useState } from "react";

import type { ResearchReferenceResponse } from "@/lib/trendora-api";
import { formatDate, formatMetric, sourceLabel } from "@/lib/format";
import { platformLabel } from "@/lib/platform";
import { publicationDay, publicationScope, publicationScopeLabel } from "@/lib/report-provenance";
import {
  YOUTUBE_THUMBNAIL_HEIGHT,
  YOUTUBE_THUMBNAIL_MIN_WIDTH,
  YOUTUBE_THUMBNAIL_WIDTH,
  youtubeThumbnailCandidates,
} from "@/lib/report-reference";

interface ReferenceCardProps {
  reference: ResearchReferenceResponse;
  window?: { date_from?: string; date_to?: string };
}

/**
 * Compact source card: an optional YouTube preview, the title, its
 * source/domain and publication date, and an Open source link stay on the
 * surface. Metrics, collection date, regional availability, source position,
 * the description, and the scope caveats sit behind one Details disclosure.
 */
export function ReferenceCard({ reference, window }: ReferenceCardProps) {
  const [candidateIndex, setCandidateIndex] = useState(0);
  const [previewFailed, setPreviewFailed] = useState(false);
  const isFacebook = reference.source_code === "facebook";
  const isYouTube = reference.source_code === "youtube";
  const title = reference.title || (isFacebook ? "Facebook post" : isYouTube ? "Untitled video" : "Untitled source");
  // Publication date is unknown unless a valid calendar day exists; the
  // formatter is only needed when it does.
  const publishedDay = publicationDay(reference.published_at);
  const collected = formatDate(reference.collected_at);
  const metric = (value: number | null | undefined) => value == null ? "Unknown" : formatMetric(value);
  const candidates = youtubeThumbnailCandidates(reference);
  const previewSrc = previewFailed ? null : candidates[candidateIndex] ?? null;
  const scope = publicationScope(reference.published_at, window);
  // A public-web result from a known platform is labelled by its hostname
  // (e.g. "Reddit · via web search"); otherwise the indexed domain is shown.
  const channel = reference.source_code === "public_web"
    ? platformLabel(reference.url) ?? reference.channel_title
    : reference.channel_title;

  // Try each candidate once: advance on a load error, or when the image is a
  // clearly undersized placeholder. Exhausting the sequence drops the preview
  // and the card stays a clean text card.
  function advancePreview() {
    if (candidateIndex + 1 >= candidates.length) setPreviewFailed(true);
    else setCandidateIndex(candidateIndex + 1);
  }

  return (
    <article className="reference-card">
      {previewSrc && (
        <div className="reference-preview">
          {/* Deliberate plain <img>: a direct first-party YouTube thumbnail, no
              Next image proxy (which would be unrestricted remote optimization),
              with a no-referrer policy. See lib/report-reference.ts. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            key={previewSrc}
            src={previewSrc}
            alt={`YouTube thumbnail for ${title}`}
            width={YOUTUBE_THUMBNAIL_WIDTH}
            height={YOUTUBE_THUMBNAIL_HEIGHT}
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={advancePreview}
            onLoad={(event) => {
              const image = event.currentTarget;
              if (image.naturalWidth > 0 && image.naturalWidth < YOUTUBE_THUMBNAIL_MIN_WIDTH) {
                advancePreview();
              }
            }}
          />
        </div>
      )}

      <div className="reference-card-top">
        <span className="source-badge">{sourceLabel(reference.source_code)}</span>
        {channel && (
          <span className="reference-channel">{channel}</span>
        )}
      </div>

      <h3 className="reference-title">{title}</h3>

      <p className="reference-date-line">
        {publishedDay === null ? "Publication date unknown" : <>Published <time dateTime={reference.published_at ?? undefined}>{formatDate(reference.published_at)}</time></>}
      </p>

      {reference.url ? (
        <a
          className="view-original"
          href={reference.url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open source
        </a>
      ) : (
        <span className="drawer-muted">Original URL unavailable.</span>
      )}

      <details className="reference-details">
        <summary>Details</summary>
        <div className="reference-details-body">
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
            <span>{collected === "—" ? "Collection date unknown" : <>Collected <time dateTime={reference.collected_at}>{collected}</time></>}</span>
            {(reference.market_contexts?.length ?? 0) > 0 && (
              <span title="Regional YouTube availability/viewability, not creator nationality, content origin, or language">
                Available in {reference.market_contexts.join(" · ")}
              </span>
            )}
            <span>Source position: {reference.source_rank ?? "Unknown"}</span>
          </div>

          <p className="drawer-muted" data-publication-scope={scope}>
            {publicationScopeLabel(scope)}. Event date unavailable;
            publication timing does not verify when a development happened.
          </p>

          {reference.source_code === "public_web" && (
            <p className="drawer-muted">Timeframe coverage is unverified for this public-web result.</p>
          )}
        </div>
      </details>
    </article>
  );
}
