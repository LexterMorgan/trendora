# Trendora Alpha v0.1

Product truth and capability limits live in [the PRD](docs/14_PRODUCT_ARCHITECTURE_REBASELINE.md).

## Direction

A research desk for collecting sources, reading findings, and keeping useful work.
The application surfaces operate; the report surface reads. Preserve the approved
rounded sans-serif wordmark and blue diagonal-cut mark. The serif logo alternative
was not selected.

## Visual system

- Cool paper `#f5f6f8`, white `#ffffff`, ink `#20252e`, secondary ink
  `#4e5867`, and cobalt `#2856b5`. Blue identifies actions and the brand.
- Self-hosted Manrope carries interface headings and controls, relating to the approved rounded
  wordmark. Editorial serif headings belong to report reading only. The wordmark
  is an image, not a replacement font. The variable font and its SIL Open Font
  License live in `web/app/fonts/`; builds and readers need no Google Fonts connection.
- A flat horizontal navigation and task-first title lead into a research workbench:
  the composer beside a source guide and real shortcuts. The report is a document
  surface. Mobile follows reading order and keeps the header on one row where it fits.
- Rounded controls and surfaces share a small radius scale. Rules divide content;
  surfaces group work. Avoid decorative cards, invented statistics, and gradients.
- Use concise sentence-case labels. Coverage and uncertainty stay visible even
  when supporting metadata is collapsed.
- ENERGY 2 / RHYTHM 2 / MOTION 1. Brief feedback follows actions; reduced motion
  removes nonessential movement. No fake progress or looping decorative animation.

## Invariants

Keep global topic/timeframe research, optional content tools, source disclosures,
the finding-support categories, citation focus management, thumbnail fallbacks,
save/recovery identity, account isolation, and planner concurrency behavior.

Logo sources are stored in `web/public/brand/`; the generated wordmark is raster.
The compact SVG mark is a geometric reconstruction for small icons.
