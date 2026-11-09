# Deployment - written, not run (Azure primary; AWS, Google Cloud, self-hosted)

Nothing in this repository has been deployed. The Terraform and Bicep stacks are validated in CI
(`terraform validate`, `terraform test` with mocked providers, tflint, checkov, `bicep build`), and the
deploy workflow is gated by the repository variable `DEPLOY_ENABLED`, which is not set.

## Resources

| Resource | Purpose | Setting that matters |
|---|---|---|
| Resource group | container for everything | one per environment |
| Log Analytics + Application Insights | logs and traces | 30-day retention |
| User-assigned managed identity | app identity | used for the model and Key Vault |
| Key Vault (RBAC, purge protection) | trace-pseudonym key and policy signing key | values set out of band, never in IaC |
| Microsoft Foundry resource (AIServices) | hosts the chat model | key auth disabled; Entra ID only |
| Model deployment `chat` | request understanding | GlobalStandard, capacity 10 (capped at 50 by validation) |
| Container Apps environment + app | the assistant API | min replicas 0, max 2; built-in Entra ID auth returns 401 to anonymous callers |
| Role assignments | least privilege | Cognitive Services OpenAI User on the model; Key Vault Secrets User on the vault |
| Diagnostic settings | audit | Foundry all logs, Key Vault audit events |

## Cost drivers (check the Azure pricing calculator before any deploy)

No cost figure is claimed here. The bill would come from:

- **Model tokens** in Microsoft Foundry, billed per token. The mock-model evaluation averages
  162.8<!-- m:final.avg_tokens --> tokens per request; a real model would use more.
- **Container Apps** consumption: billed per vCPU-second and GiB-second while running; it scales to
  zero when idle and has a monthly free grant.
- **Log Analytics** ingestion per GB.
- **Key Vault** operations (small).

## How it would be deployed (only after approval)

1. Create an Entra ID app registration for OIDC from GitHub and one for API callers.
2. Set repository variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, and add a
   required reviewer to the `dev` environment.
3. Build and push the image from the `Dockerfile` to a registry of your choice.
4. Set `DEPLOY_ENABLED=true` and run the `deploy` workflow by hand (Terraform or Bicep).
5. The smoke test checks that an anonymous call is refused with 401.
6. Switch `HARROWGATE_LLM` from `mock` to `foundry` only after the evaluation passes against the real
   model.

## Not included (Planned)

Private endpoints and VNet integration, a managed database for journey state, OpenTelemetry export,
and an image registry.

## Other options (written, not run)

The core imports no cloud SDK. `HARROWGATE_PROVIDER` picks a model adapter from
`harrowgate/providers.py`: `mock` (default), `azure` (Microsoft Foundry), `aws`, `gcp` or
`selfhosted` (any OpenAI-compatible server). Cloud SDKs are imported only inside their adapter. See
[ADR 0010](adr/0010-cloud-neutral-core.md) and the [cost comparison](cloud-options.md).

| Stack | Folder | What it creates | Checked in CI |
|---|---|---|---|
| AWS | `infra/aws` | KMS key, private image registry (immutable, scanned), encrypted logs, secret, ECS Fargate task with read-only root filesystem and no public IP, role that may invoke one model only | fmt, validate, tflint, checkov |
| Google Cloud | `infra/gcp` | service account, Artifact Registry (immutable), Secret Manager, Cloud Run with internal ingress only | fmt, validate, tflint, checkov |
| Self-hosted | `infra/onprem` | docker compose: the API plus an OpenAI-compatible model server on an NVIDIA GPU, internal network, policy key as a file secret (`HARROWGATE_POLICY_KEY_FILE`) | not run |

None of these has a deploy workflow; they are references and are never applied from this repo.
