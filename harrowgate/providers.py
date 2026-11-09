"""Cloud-neutral model access. The core only knows `complete(task, payload) -> str`.

    HARROWGATE_PROVIDER = mock (default) | azure | aws | gcp | selfhosted

Only the mock runs in this repository. The four real adapters are written, not run: they show the
request shape and the identity each platform expects, and they import any cloud SDK lazily so the
core never depends on one. Every adapter's answer still goes through `llm.structured` (schema,
one repair, escalate), so changing provider cannot weaken validation.
"""

from __future__ import annotations

import json
import os
import urllib.request

from .llm import FoundryLLM, MockLLM

SYSTEM = "Return only JSON that matches the schema in the request."


class SelfHostedLLM:  # pragma: no cover - needs a running OpenAI-compatible server; written, not run
    """Open model on your own NVIDIA servers behind an OpenAI-compatible API (for example vLLM)."""

    name = "selfhosted"

    def __init__(self) -> None:
        self.url = os.environ["SELFHOSTED_BASE_URL"].rstrip("/") + "/v1/chat/completions"
        self.model = os.environ.get("SELFHOSTED_MODEL", "open-8b-instruct")

    def complete(self, task: str, payload: dict) -> str:
        body = {"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": json.dumps({"task": task, **payload})}]}
        req = urllib.request.Request(self.url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - fixed internal URL from config
            return json.loads(r.read())["choices"][0]["message"]["content"]


class AwsLLM:  # pragma: no cover - needs an AWS account and model access; written, not run
    """Managed model through the Bedrock Converse API, using the task role (no keys in code)."""

    name = "aws"

    def __init__(self) -> None:
        import boto3  # lazy: the core does not depend on any cloud SDK
        self.client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        self.model = os.environ["AWS_MODEL_ID"]

    def complete(self, task: str, payload: dict) -> str:
        out = self.client.converse(modelId=self.model, system=[{"text": SYSTEM}],
                                   messages=[{"role": "user", "content": [{"text": json.dumps({"task": task,
                                                                                               **payload})}]}],
                                   inferenceConfig={"temperature": 0})
        return out["output"]["message"]["content"][0]["text"]


class GcpLLM:  # pragma: no cover - needs a Google Cloud project; written, not run
    """Managed model through Vertex AI, using the service account attached to Cloud Run."""

    name = "gcp"

    def __init__(self) -> None:
        from google import genai  # lazy import
        self.client = genai.Client(vertexai=True, project=os.environ["GCP_PROJECT"],
                                   location=os.environ.get("GCP_REGION", "europe-west2"))
        self.model = os.environ["GCP_MODEL_ID"]

    def complete(self, task: str, payload: dict) -> str:
        out = self.client.models.generate_content(
            model=self.model, contents=json.dumps({"task": task, **payload}),
            config={"system_instruction": SYSTEM, "temperature": 0, "response_mime_type": "application/json"})
        return out.text


PROVIDERS = {"mock": MockLLM, "azure": FoundryLLM, "aws": AwsLLM, "gcp": GcpLLM, "selfhosted": SelfHostedLLM}


def make_provider(name: str | None = None, faults: dict | None = None):
    name = name or os.environ.get("HARROWGATE_PROVIDER", "mock")
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name}; choose one of {sorted(PROVIDERS)}")
    return MockLLM(faults) if name == "mock" else PROVIDERS[name]()
