"""Deterministic compaction of the EvidencePack sent to the interpretation model.

Only the AI-input subset is compacted. The report's stored ``EvidencePack`` (and
everything saved with it: analyses, observations, metrics, pattern identities) is
never modified, so saved reports and snapshots are unaffected.

The subset is what the model may cite: grounding and text-support validation run
against this same subset, so a citation the model never saw cannot validate.
Compaction removes redundant representations of the same evidence, bounds
repetitive text at the input boundary (whitespace-only text stays blank), and
selects references source-first, then by domain within each source, so one large
source batch cannot crowd out the others. No tokenizer, no ranking framework, no
extra AI call.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from trendora.research.evidence import (
    EvidenceFact,
    EvidenceField,
    ReferenceAnalysis,
)
from trendora.research.interpretation import EvidencePack

# A bounded input keeps the request small. Selection is source-fair: sources are
# taken in turn, then domains within a source, until this cap is reached. A cap
# below the source count cannot represent every source.
MAX_INPUT_REFERENCES = 24
MAX_TITLE_CHARS = 200
MAX_DESCRIPTION_CHARS = 600
_TRUNCATION_SUFFIX = "…"

# Kept: the fields that can support a finding (text), plus publication date and
# channel/domain context. Dropped: url, collected_at, market context/basis, and
# source rank (metadata-only), and every engagement count. ``collected_at`` is
# retrieval time, not publication, so excluding it also keeps freshness honest.
_KEPT_FIELDS = (
    EvidenceField.TITLE,
    EvidenceField.DESCRIPTION,
    EvidenceField.PUBLISHED_AT,
    EvidenceField.CHANNEL_TITLE,
)
_TEXT_LIMITS = {
    EvidenceField.TITLE: MAX_TITLE_CHARS,
    EvidenceField.DESCRIPTION: MAX_DESCRIPTION_CHARS,
}


def _fact_value(analysis: ReferenceAnalysis, field: EvidenceField) -> object:
    for fact in analysis.facts:
        if fact.field is field:
            return fact.value
    return None


def truncate_text(text: str, limit: int) -> str:
    """Bound long text at the input boundary, preferring a word boundary.

    Surrounding whitespace is trimmed before clipping, so whitespace-only text
    stays blank and can never turn into a marker that reads as retained content.
    The marker is appended only when real text is kept and content was actually
    omitted, so an empty or whitespace-only result stays empty.
    """
    trimmed = text.strip()
    if len(trimmed) <= limit:
        return trimmed
    clipped = trimmed[:limit]
    space = clipped.rfind(" ")
    if space > 0:
        clipped = clipped[:space]
    clipped = clipped.rstrip()
    if not clipped:
        return ""
    return clipped + _TRUNCATION_SUFFIX


def _compact_facts(analysis: ReferenceAnalysis) -> tuple[EvidenceFact, ...]:
    facts = []
    for field in _KEPT_FIELDS:
        value = _fact_value(analysis, field)
        limit = _TEXT_LIMITS.get(field)
        if limit is not None and isinstance(value, str):
            value = truncate_text(value, limit)
        facts.append(EvidenceFact(analysis.reference, field, value))
    return tuple(facts)


def _domain_key(analysis: ReferenceAnalysis) -> str:
    url = _fact_value(analysis, EvidenceField.URL)
    if isinstance(url, str) and url:
        try:
            host = urlsplit(url).hostname
        except ValueError:
            host = None
        if host:
            return host.lower()
    channel = _fact_value(analysis, EvidenceField.CHANNEL_TITLE)
    if isinstance(channel, str) and channel.strip():
        return channel.strip().lower()
    return analysis.reference.source_code


def _normalized_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).lower()


def collapse_exact_duplicates(
    analyses: tuple[ReferenceAnalysis, ...],
) -> tuple[ReferenceAnalysis, ...]:
    """Drop later references whose normalized title AND description repeat.

    Deterministic and conservative: only exact (case/whitespace-insensitive)
    repeats of a *substantive* description collapse, so the same syndicated page
    is not presented as several independent developments. A blank description is
    never treated as a duplicate key, so unrelated records that merely share a
    generic title are all kept. Distinct wording is never merged, and an exact
    textual repeat is not evidence of corroboration or of a shared event.
    """
    seen: set[tuple[str, str]] = set()
    kept: list[ReferenceAnalysis] = []
    for analysis in analyses:
        title = _normalized_text(_fact_value(analysis, EvidenceField.TITLE))
        description = _normalized_text(_fact_value(analysis, EvidenceField.DESCRIPTION))
        if description:
            key = (title, description)
            if key in seen:
                continue
            seen.add(key)
        kept.append(analysis)
    return tuple(kept)


def _interleave_domains(domains: list[list[ReferenceAnalysis]]) -> list[ReferenceAnalysis]:
    """Round-robin across one source's domains, preserving order inside each."""
    interleaved: list[ReferenceAnalysis] = []
    index = 0
    while any(index < len(items) for items in domains):
        for items in domains:
            if index < len(items):
                interleaved.append(items[index])
        index += 1
    return interleaved


def select_analyses(
    analyses: tuple[ReferenceAnalysis, ...], limit: int = MAX_INPUT_REFERENCES
) -> tuple[ReferenceAnalysis, ...]:
    """Deterministic, source-fair selection of at most ``limit`` analyses.

    Exact duplicates collapse first. Everything that fits keeps its original
    order. Otherwise references are taken round-robin across sources in
    first-seen order, and inside each source round-robin across domains in
    first-seen order, preserving reference order within a domain. Exhausted
    sources and domains are skipped so their slots go to whoever remains.

    The guarantee is bounded by ``limit``. A limit smaller than the number of
    sources fills in first-seen source order rather than claiming full coverage,
    and a nonpositive limit selects nothing.
    """
    analyses = collapse_exact_duplicates(analyses)
    if limit <= 0:
        return ()
    if len(analyses) <= limit:
        return analyses
    sources: dict[str, dict[str, list[ReferenceAnalysis]]] = {}
    for analysis in analyses:
        domains = sources.setdefault(analysis.reference.source_code, {})
        domains.setdefault(_domain_key(analysis), []).append(analysis)
    queues = [_interleave_domains(list(domains.values())) for domains in sources.values()]
    selected: list[ReferenceAnalysis] = []
    cursors = [0] * len(queues)
    while len(selected) < limit:
        progressed = False
        for position, queue in enumerate(queues):
            if len(selected) >= limit:
                break
            cursor = cursors[position]
            if cursor < len(queue):
                selected.append(queue[cursor])
                cursors[position] = cursor + 1
                progressed = True
        if not progressed:
            break
    return tuple(selected)


def build_interpretation_input(pack: EvidencePack) -> EvidencePack:
    """Compact, non-destructive view of ``pack`` for the interpretation request.

    Keeps title/description (bounded), publication date, and channel per
    selected reference. Drops per-reference structural observations,
    metadata-only or engagement facts, and every pattern aggregate: this path
    exists to produce text-supported research findings, and pattern counts are
    computed over the full pack while the request carries a reduced reference
    subset. Supplying them would both misstate the subset and produce generation
    counts that differ from the full-pack counts a saved report later resolves
    the same citation against. Patterns and every dropped fact remain in the
    stored pack and in the legacy/content-analysis path.
    """
    analyses = tuple(
        ReferenceAnalysis(
            reference=analysis.reference,
            analysis_basis=analysis.analysis_basis,
            facts=_compact_facts(analysis),
            observations=(),
        )
        for analysis in select_analyses(pack.analyses)
    )
    return EvidencePack(analyses, (), research_query=pack.research_query)


def payload_size(pack: EvidencePack) -> int:
    """UTF-8 byte size of the serialized evidence payload (a size proxy)."""
    from trendora.research.ai_provider import evidence_pack_to_payload
    import json

    return len(
        json.dumps(
            evidence_pack_to_payload(pack), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    )
