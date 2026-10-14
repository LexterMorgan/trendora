/**
 * Presentation helpers for source references.
 *
 * A reference carries no stored image field. The only trustworthy image
 * metadata already serialized is the official YouTube video id
 * (`content_external_id`), from which YouTube's first-party thumbnail host
 * serves deterministic images. Public-web results have no first-party image
 * (their only candidate is an untrusted third-party URL), so they get no
 * preview.
 *
 * The id is validated against the exact YouTube id shape before it is placed
 * in a URL, so no arbitrary path or host can be constructed. Candidate order
 * runs highest to lowest resolution; availability of higher resolutions is not
 * guaranteed, so the card advances through the sequence on failure.
 */

const YOUTUBE_VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
const YOUTUBE_IMAGE_HOST = "https://i.ytimg.com";
const THUMBNAIL_FILES = ["maxresdefault.jpg", "hqdefault.jpg", "mqdefault.jpg"] as const;

/** Reserved preview dimensions for the 16:9 preview box. */
export const YOUTUBE_THUMBNAIL_WIDTH = 320;
export const YOUTUBE_THUMBNAIL_HEIGHT = 180;

/** Anything narrower than this is YouTube's ~120px "no thumbnail" placeholder. */
export const YOUTUBE_THUMBNAIL_MIN_WIDTH = 200;

/**
 * Ordered first-party thumbnail candidates for a reference, highest resolution
 * first, or `[]` when the reference is not a YouTube video with a valid id.
 * Never built from any other field.
 */
export function youtubeThumbnailCandidates(reference: {
  source_code: string;
  content_external_id: string;
}): string[] {
  if (reference.source_code !== "youtube") return [];
  if (!YOUTUBE_VIDEO_ID.test(reference.content_external_id)) return [];
  const id = reference.content_external_id;
  return THUMBNAIL_FILES.map((file) => `${YOUTUBE_IMAGE_HOST}/vi/${id}/${file}`);
}
