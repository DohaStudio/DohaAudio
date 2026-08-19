# Runtime 계약

> 문서 상태: [구현]
> Fake Runtime·HTTP API: [구현]
> 실제 모델 worker·영속 persistence: [미구현]

DohaAudio Runtime Foundation은 capability 작업의 계약을 실행하는 독립 Provider Runtime입니다. 현재 `FakeAudioProvider`만 등록되며 실제 모델을 load하거나 외부 Provider를 호출하지 않습니다. DohaMusic만 외부 Orchestrator로서 Runtime을 호출하는 경계를 유지합니다.

## 구현된 계약

- Job 생성과 idempotency key
- 상태 조회와 progress
- 취소 요청과 최종 취소 상태
- 명시적 재시도와 attempt 식별자
- 구조화된 오류 code, 재시도 가능 여부와 안전한 message
- Health·readiness·capability 조회
- Provider API contract version
- Artifact ID·URI, checksum, MIME type와 provenance 반환

로컬 절대 경로를 외부 계약으로 반환하지 않습니다. Runtime 내부 경로는 환경 변수로 주입하고 외부에는 Artifact ID 또는 승인된 URI만 노출합니다.

## 상태와 실행

```text
queued → running → succeeded
                 → failed
                 → cancelled
queued → cancelled
```

종료 상태는 불변입니다. Retry는 원본 상태와 오류를 보존한 채 새 `job_id`, `retry_of_job_id`와 증가한 `attempt`를 갖습니다. 동일 idempotency key와 동일 canonical request는 기존 Job을 replay하고 요청이 다르면 conflict로 거부해 부분 Job을 만들지 않습니다.

`CreateJob`은 `queued` 상태를 반환합니다. 이 Foundation에는 worker·queue가 없으므로 자동 실행하지 않으며 embedding code와 test가 `AudioRuntime.run_job(job_id)`를 명시적으로 호출합니다. Fake Runtime의 queued·running 취소는 즉시 최종 `cancelled`로 처리합니다. `progress_percent=100`은 Artifact 등록 전까지 `running`일 수 있습니다.

## HTTP API

| 기능 | Method·Path |
|---|---|
| GetCapabilities | `GET /api/v1/providers/audio/capabilities` |
| CreateJob | `POST /api/v1/providers/audio/jobs` |
| GetJobStatus | `GET /api/v1/providers/audio/jobs/{job_id}` |
| CancelJob | `POST /api/v1/providers/audio/jobs/{job_id}/cancel` |
| RetryJob | `POST /api/v1/providers/audio/jobs/{job_id}/retry` |
| GetResult | `GET /api/v1/providers/audio/jobs/{job_id}/result` |
| GetModelManifest | `GET /api/v1/providers/audio/model-manifests/{model_manifest_id}` |
| Health | `GET /api/v1/providers/audio/health` |
| Readiness | `GET /api/v1/providers/audio/readiness` |

`api_contract_version`은 `1.0`입니다. `Idempotency-Key` header는 선택 사항이며 body의 `idempotency_key`를 canonical 값으로 사용합니다. 둘 다 있으면 일치해야 합니다. 오류는 `error_code`, 안전한 `message`, `retryable`, `stage`, `details_id`만 외부에 공개합니다.

## 현재 범위 밖

GPU admission control, 여러 Provider 실행 순서, Workspace Selection과 최종 AssetVersion 등록은 DohaMusic 책임입니다. 실제 모델 load/unload, Dataset, Checkpoint, 영속 DB, 분산 queue, 인증, 배포와 network DohaMusic 통합은 구현하지 않았습니다.

## 관련 결정

- [ADR-002 Provider Contract](../10-decisions/ADR-002-provider-contract.md)
- [ADR-004 Artifact Lifecycle](../10-decisions/ADR-004-artifact-lifecycle.md)
- [ADR-005 Pre-Training Runtime Foundation](../10-decisions/ADR-005-pre-training-runtime-foundation.md)
