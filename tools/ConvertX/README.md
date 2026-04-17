# ConvertX Integration Home

This directory holds the local runtime home for the ConvertX backend used by
Agent Tools Gateway.

## Contents

```text
tools/ConvertX/
  README.md
  data/         # mounted into the ConvertX container at /app/data
  work/
    input/      # allowed input root
    output/     # allowed output root
    tmp/        # temp root
```

## Notes

- The upstream ConvertX source repository stays outside this repo.
- Runtime data under `data/` and `work/` is gitignored.
- The gateway backend key is `convertx`, while the user-facing integration
  home stays at `tools/ConvertX`.
