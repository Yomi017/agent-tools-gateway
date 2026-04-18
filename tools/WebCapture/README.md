# WebCapture Integration Home

This directory holds the local runtime home for the Browserless-backed
`webcapture` backend used by Agent Tools Gateway.

## Contents

```text
tools/WebCapture/
  README.md
  work/
    output/     # allowed output root
    tmp/        # temp root
```

## Notes

- Browserless stays external to this repo and runs as a separate container.
- Runtime files under `work/` are gitignored.
- The gateway backend key is `webcapture`, while the user-facing integration
  home stays at `tools/WebCapture`.
