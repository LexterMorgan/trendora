interface MarketCaveatProps {
  market: string;
  executedSources: string[];
}

/**
 * Truthful market framing per executed source. YouTube market context is
 * regional availability/viewability, not creator nationality or content
 * origin. Facebook collection is one explicit Page + date range; topic and
 * market do not filter collected posts. No recognized source → no caveat.
 */
export function MarketCaveat({ market, executedSources }: MarketCaveatProps) {
  if (executedSources.includes("youtube")) {
    return (
      <aside className="market-caveat">
        <p>
          <strong>YouTube market context: {market}</strong> — reflects regional
          availability/viewability and does not establish creator nationality or
          content origin.
        </p>
      </aside>
    );
  }
  if (executedSources.includes("facebook")) {
    return (
      <aside className="market-caveat">
        <p>
          <strong>Facebook market context: {market}</strong> — collection used
          the explicit Facebook Page and date range; topic and market did not
          filter the collected Page posts. The selected market is report
          context and does not prove audience, publisher, or content location.
        </p>
      </aside>
    );
  }
  return null;
}
