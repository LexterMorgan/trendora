# Kurage research shell adaptation

The research landing shell in this directory adapts the **Kurage Dashboard**
template by HorizonX (v1.0.0, October 2026). The template was supplied by the
project owner through a HorizonX membership. The membership licence permits
adapting the template for personal and client work, but it does not permit
redistributing or publicly sharing the original template source files.

## What was retained

- Near-black atmosphere with cyan/violet highlights.
- Fine background grid and the canvas ASCII ocean.
- The original procedural jellyfish geometry, tentacles, drifting, glyph
  ramps, mosaic tiles, pointer response, and 30fps loop.
- Narrow collapsible rail, mobile drawer, centred composition, headline
  treatment, translucent composer proportions, and compact chips.
- Native canvas/requestAnimationFrame and browser animation APIs. No animation
  library was added.

## What was adapted

- Kurage branding, Marcelo identity, assistant modes, attachments, microphone,
  fake history/library/activity, profile, and command palette were removed.
- The rail now uses real Trendora destinations: New research, Reports, Planner,
  Explore sources, motion control, sign out, and sidebar collapse.
- History links to `/past-reports`; no second prompt-history store exists.
- The composer now owns Trendora's topic-first landing step. Continue opens the
  existing timeframe setup; no AI/search call is made on the landing screen.
- The headline rotates only truthful Trendora research phrases and pauses on
  composer focus/draft, hidden tabs, reduced motion, or the motion control.
- The ocean is scoped to the landing view. It unmounts on setup, results,
  reports, planner, and signed-out pages.
- Styles live in `web/app/research-shell.css` and are scoped to
  `.research-shell`; report, planner, form, and auth styles are not rewritten.

## Publication constraint

Do not commit the original ZIP, its agent-instruction files, or an untouched
standalone copy of the template. This adaptation remains part of the private
Trendora application. Attribution is retained here and in the landing footer.

## Landing theme

The landing shell supports a persisted dark/light theme. The jellyfish geometry,
RAMP/SNOW glyphs, tentacle physics, and animation loop are unchanged. The ocean
uses a dark cyan/violet palette in dark mode and a dark-ink cyan/violet palette
in light mode so the ASCII remains legible against the light shell. Setup,
results, Reports, Planner, Discover, and auth are not themed by this change.

## Shared shell

The shell is now shared across Research (home, setup, results), Reports,
Planner, and Explore sources. The rail and topbar are the same on those pages;
the ASCII ocean and landing composition remain home-only. Theme and rail
preferences persist through localStorage, and unmigrated report/planner-post
auth surfaces keep their existing Header and paper styles.

## Persistent shell state

Theme and rail width are owned once by `ShellStateProvider` in the root layout.
The desktop top-left panel button and the rail-foot panel button call the same
toggle and persist the same `trendora:research-rail` value. Mobile keeps its
separate drawer menu button. The ocean and motion controls remain home-only.

## Shared static grid

Non-home shell pages use the same 1px grid spacing as the home ocean layer,
without the ocean or its mask. The dark line is `rgba(255,255,255,0.028)` and
the light line is `rgba(32,37,46,0.06)`, both on a 10px by 15px step. The
background is static; home keeps the animated jellyfish ocean.
