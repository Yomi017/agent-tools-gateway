# SearXNG Integration Home

This directory holds the local runtime home for the `searxng` backend used by
Agent Tools Gateway.

## Contents

```text
tools/SearXNG/
  README.md
  config/
    settings.yml  # mounted into the SearXNG container
  data/           # mounted into the SearXNG container at /var/cache/searxng
```

## Notes

- SearXNG stays external to this repo and runs as a separate container.
- Runtime cache under `data/` is gitignored.
- The gateway backend key is `searxng`, while the user-facing integration home
  stays at `tools/SearXNG`.
- v1 intentionally supports keyword search only. It does not expose
  suggestions, autocomplete, engine management, or raw upstream JSON.
- The bundled `settings.yml` keeps the instance private-first and enables
  `format=json` so the gateway can use the official SearXNG Search API.
