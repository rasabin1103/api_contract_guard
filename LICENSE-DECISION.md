# Engine compatibility and distribution decision

Decision date: 2026-10-20. Use **oasdiff 1.34.0**, invoked as an independent executable through a replaceable Python protocol. No hosted oasdiff service, license key or ASE service is required. Verified against the release metadata, downloaded Windows amd64 release archive and upstream checksum manifest. The local binary reports `oasdiff version 1.34.0` and has been used by the automated semantic fixtures and CLI.

Sources:

- [Pinned source and release](https://github.com/oasdiff/oasdiff/releases/tag/v1.34.0)
- [Apache-2.0 license](https://github.com/oasdiff/oasdiff/blob/v1.34.0/LICENSE)
- [OpenAPI 3.1 support and caveats](https://github.com/oasdiff/oasdiff/blob/main/docs/OPENAPI-31.md)
- [Compatibility rules](https://github.com/oasdiff/oasdiff/tree/v1.34.0/docs/checks)
- [Pinned Go module](https://github.com/oasdiff/oasdiff/blob/v1.34.0/go.mod)

The parser `openapi-spec-validator` validates 3.0 and 3.1; fixtures exercise both. oasdiff's documented 3.1 coverage is incomplete for dynamic references/anchors and reusable components.pathItems. This application rejects these constructs rather than silently accepting an incomplete comparison. OpenAPI 2.x and 3.2 are rejected by the import policy. The adapter uses automatic dialect upgrade for 3.0/3.1 comparisons. Compatibility classifications follow engine levels, not a textual diff.

Local Windows/Linux/macOS installers download official release archives and verify SHA-256 against the release manifest. This protects archive integrity relative to GitHub's release, not against a compromised upstream release account. Docker compiles the pinned module in a separate Go builder, then copies the executable into the Python image. Runtime pin verification prevents accidental use of another version. Windows amd64 execution and Linux amd64 Docker builds/startup have been verified; see docs/VALIDATION.md. The macOS/ARM installers are provided but were not executed here.

Apache-2.0 permits commercial use and redistribution subject to its conditions. Distributions containing oasdiff must include its license, applicable upstream notices/attributions and notices for modifications. The unmodified upstream license is retained in `third-party/oasdiff-LICENSE`; Docker copies it into the runtime. Review all transitive Go-module and Python/npm license obligations before publishing a binary distribution. No trademark endorsement is implied. The owner must choose the distribution license for this application's original code; no open-source grant or commercial licensing decision is made on their behalf.
