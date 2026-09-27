"""Public extension contracts. No commercial service dependency in the core.

Implementations must provide their own authenticated tenancy, authorization,
durability, idempotency and key custody. These ports are not invoked automatically.
"""
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

API_VERSION = 'project-harness-extension-v1'


@dataclass(frozen=True)
class RepositoryScope:
    organization_id: str
    repository_id: str
    store_id: str


class AuditSink(Protocol):
    def append(self, scope: RepositoryScope, events: Sequence[Mapping], *, idempotency_key: str) -> str:
        """Persist an authenticated batch, returning its durable server checkpoint."""
        ...


class EvidenceStore(Protocol):
    def put(self, scope: RepositoryScope, *, sha256: str, content: bytes) -> str: ...
    def get(self, scope: RepositoryScope, *, sha256: str) -> bytes: ...


class PolicyPackProvider(Protocol):
    def fetch(self, scope: RepositoryScope, *, digest: str) -> bytes:
        """Return pinned policy bytes; callers must verify digest and signature."""
        ...


class AttestationVerifier(Protocol):
    def verify(self, envelope: bytes, *, trusted_issuers: Sequence[str]) -> Mapping:
        """Verify signature, issuer, subject digest and validity, failing closed."""
        ...
