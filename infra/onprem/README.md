# Self-hosted option (written, not run)

For tenants whose data must stay on site. One small NVIDIA server (a single 24 GB GPU is enough for
an 8B open model in this design, because rule code and templates replace most model calls) runs an
OpenAI-compatible model server; the assistant talks to it with `HARROWGATE_PROVIDER=selfhosted`.

- The model server sits on an internal-only network; only the API port is published, on localhost.
- Put a reverse proxy with TLS and your identity provider in front of the API before any real use.
- Model weights are mounted read-only; pin the server image by digest.
- The policy key comes from a file secret, never an environment literal.
- Capacity and cost figures in `docs/cloud-options.md` are estimates; load-test before buying hardware.
