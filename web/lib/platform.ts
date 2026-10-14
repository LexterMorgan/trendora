/**
 * Public-social platform labels, derived only from a result URL.
 *
 * Exact hostname/domain boundaries: a host matches only when it is the domain
 * or a subdomain of it, so `reddit.com.evil.example` is never Reddit. Aliases
 * are explicit; short links and redirect hosts are never followed or guessed.
 * Used to label a `public_web` result as e.g. "Reddit · via web search" while
 * keeping the original URL and citation identity.
 */

const PLATFORM_DOMAINS: ReadonlyArray<readonly [string, readonly string[]]> = [
  ["Reddit", ["reddit.com"]],
  ["TikTok", ["tiktok.com"]],
  ["Instagram", ["instagram.com"]],
  ["X", ["x.com", "twitter.com"]],
  ["LinkedIn", ["linkedin.com"]],
  ["Facebook", ["facebook.com"]],
];

export function platformForUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  let host: string;
  try {
    host = new URL(url).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return null;
  }
  if (!host) return null;
  for (const [platform, domains] of PLATFORM_DOMAINS) {
    for (const domain of domains) {
      if (host === domain || host.endsWith(`.${domain}`)) return platform;
    }
  }
  return null;
}

/** "Reddit · via web search", or null when the URL is not a known platform. */
export function platformLabel(url: string | null | undefined): string | null {
  const platform = platformForUrl(url);
  return platform ? `${platform} · via web search` : null;
}
