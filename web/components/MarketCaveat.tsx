interface MarketCaveatProps {
  market: string;
}

/**
 * Truthful market framing. YouTube market context is regional
 * availability/viewability, not creator nationality or content origin.
 */
export function MarketCaveat({ market }: MarketCaveatProps) {
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
