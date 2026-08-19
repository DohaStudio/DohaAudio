"""Single-job execution worker boundary for deterministic Provider fixtures."""

from __future__ import annotations

from dataclasses import dataclass

from dohaaudio.contracts import JobResponse
from dohaaudio.repositories import JobRepository
from dohaaudio.services import JobApplicationService


@dataclass(frozen=True)
class ExecutionWorker:
    jobs: JobRepository
    service: JobApplicationService
    worker_id: str = "worker-foundation"
    lease_seconds: int = 60

    def run_once(self) -> JobResponse | None:
        claimed = self.jobs.claim_next(self.worker_id, self.lease_seconds)
        if claimed is None:
            return None
        assert claimed.claim_token is not None
        return self.service.execute_claimed(claimed.job_id, claimed.claim_token)

    def recover_stale(self) -> tuple[str, ...]:
        return self.jobs.recover_stale()
