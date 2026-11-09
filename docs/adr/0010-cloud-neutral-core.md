# ADR 0010: Cloud-neutral core with provider adapters

**Status:** accepted

**Context.** Microsoft Foundry on Azure is the primary target, but buyers run AWS, Google Cloud or
their own GPU servers, often for data-location reasons.

**Decision.** The core package imports no cloud SDK. One small model port (`complete(task, payload)`)
has adapters: mock (default, used in CI), Microsoft Foundry, AWS, Google Cloud and any
OpenAI-compatible self-hosted server. SDKs are imported lazily inside each adapter, and a test checks
none is loaded by the core. Infrastructure is written per target (`infra/terraform` and `infra/bicep`
for Azure, `infra/aws`, `infra/gcp`, `infra/onprem`), validated and scanned in CI, never applied.

**Consequences.** Switching provider is a release (layer 19) gated by the same evaluation. Provider
features beyond the port (for example built-in safety filters) are optional extras, not dependencies.
Cost differences are compared in `docs/cloud-options.md` with dated, estimated prices.
