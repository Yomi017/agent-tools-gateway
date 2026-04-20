# Docling Integration Home

This directory holds the local runtime home for the `docling` backend used by
Agent Tools Gateway.

## Contents

```text
tools/Docling/
  README.md
  work/
    input/      # allowed input root
    output/     # allowed output root
    tmp/        # temp root
```

## Notes

- Docling Serve stays external to this repo and runs as a separate container.
- The default compose stack keeps raw Docling internal-only. Host access to
  `127.0.0.1:5001` is reserved for the optional `docker-compose.debug.yml`
  override.
- Runtime files under `work/` are gitignored.
- The gateway backend key is `docling`, while the user-facing integration home
  stays at `tools/Docling`.
- v1 intentionally supports only one local input file per request and one
  single-file output result.
- Remote URL sources, batch conversion, zip results, and `html_split_page`
  are intentionally out of scope for this integration.
