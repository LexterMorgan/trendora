interface MarketCaveatProps {
  markets: string[];
  executedSources: string[];
}

/**
 * Truthful market framing per executed source. YouTube market context is
 * regional availability/viewability, not creator nationality or content
 * origin. Facebook collection is one explicit Page + date range; topic and
 * market do not filter collected posts. No recognized source → no caveat.
 */
export function MarketCaveat({ markets, executedSources }: MarketCaveatProps) {
  if (executedSources.includes("youtube")) {
    if (!markets.length) {
      return (
        <aside className="market-caveat">
          <p>
            <strong>Global search</strong>: no country restriction was applied.
            Results are not comprehensive worldwide coverage, and YouTube
            availability does not establish creator nationality or content
            origin.
          </p>
        </aside>
      );
    }
    return (
      <aside className="market-caveat">
        <p>
          <strong>YouTube market context: {markets.join(", ")}</strong> reflects
          regional availability/viewability and does not establish creator
          nationality or content origin.
        </p>
      </aside>
    );
  }
  if (executedSources.includes("facebook")) {
    return (
      <aside className="market-caveat">
        <p>
          <strong>Facebook market context: {markets.join(", ")}</strong>:
          collection used the explicit Facebook Page and date range; topic and
          market did not filter the collected Page posts. The selected markets
          are report context and do not prove audience, publisher, or content
          location.
        </p>
      </aside>
    );
  }
  return null;
}
