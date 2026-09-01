export function EmptyState() {
  return (
    <section className="empty-state" aria-label="Empty research results">
      <h2 className="section-title">No references</h2>
      <p>
        No matching YouTube references were found for this research request.
        Try a broader topic wording or a wider date range.
      </p>
    </section>
  );
}
