# Self-hosted SearXNG for Trendora public-web discovery

Trendora can discover public web pages through a locally hosted
[SearXNG](https://docs.searxng.org/) instance instead of a paid search API.
This directory holds the minimal configuration for that instance.

**Status on this machine:** no container runtime (Docker/Podman/Colima) is
installed, so this instance was not started here. The Trendora adapter and its
mocked tests are complete and backend selection is wired; starting SearXNG is
the one remaining operator step.

## Start

Requires an existing container runtime. The image is the official one:

```bash
docker run --rm -d --name trendora-searxng \
  -p 127.0.0.1:8888:8080 \
  -v "$PWD/deploy/searxng:/etc/searxng:ro" \
  -e SEARXNG_SECRET="$(openssl rand -hex 32)" \
  docker.io/searxng/searxng:latest
```

- Binds to loopback only (`127.0.0.1:8888`) and maps to the container's 8080.
- `SEARXNG_SECRET` is generated locally and never committed.
- The config is mounted read-only; the official image's defaults supply the
  engine set.

Verify JSON is enabled:

```bash
curl -s 'http://127.0.0.1:8888/search?q=test&format=json' | head -c 200
```

## Point Trendora at it

In `.env` (backend):

```bash
TRENDORA_WEB_SEARCH_BACKEND=searxng   # or "auto" to prefer SearXNG
SEARXNG_URL=http://127.0.0.1:8888
```

`TRENDORA_WEB_SEARCH_BACKEND` accepts `auto`, `serper`, `searxng`, or `none`.
A named backend never silently falls back to a different (paid) provider.

## Stop

```bash
docker stop trendora-searxng
```

`--rm` removes the container on stop. No data volume is used, so nothing
persists.

## Notes

- This is a search-only integration: Trendora normalizes result URLs, titles,
  snippets, and source identities. Reading the full text of discovered pages
  (with its own untrusted-URL fetch/SSRF boundary) is deferred; see the
  Trendora report for details.
- The SearXNG endpoint is operator-configured and separate from the untrusted
  result URLs Trendora stores.
