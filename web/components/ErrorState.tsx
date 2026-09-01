const CODE_MESSAGES: Record<string, string> = {
  invalid_request:
    "The research request was not valid. Check the form and try again.",
  invalid_research_request:
    "The research request could not be validated. Review the topic, market, dates, and result limit.",
  research_no_coverage:
    "No requested source can satisfy this research capability.",
  research_source_not_configured:
    "The research source is not configured on the server. The backend may need a YouTube API key.",
  research_upstream_error:
    "YouTube research is temporarily unavailable. Please try again later.",
  backend_unreachable:
    "The Trendora backend could not be reached. Make sure the backend is running.",
  backend_not_configured:
    "The Trendora backend is not configured (TRENDORA_API_BASE_URL is missing).",
  internal_error: "An unexpected error occurred.",
};

interface ErrorStateProps {
  code: string;
  message: string;
}

export function ErrorState({ code, message }: ErrorStateProps) {
  const readable = CODE_MESSAGES[code] ?? message;
  return (
    <section className="error-state" role="alert">
      <h2 className="section-title">Research could not be completed</h2>
      <p>{readable}</p>
      {code && <p className="error-code">Error code: {code}</p>}
    </section>
  );
}
