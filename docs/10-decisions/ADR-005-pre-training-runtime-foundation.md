# ADR-005: 학습 전 Runtime Foundation

- 상태: 승인됨 [구현]
- 작성일: 2026-08-19
- 관련 명세: DohaStudio 공통 Provider·Job·Artifact·Model Manifest 계약 `0.1.0`

## 배경과 문제

실제 Dataset과 Checkpoint를 준비하기 전에 DohaAudio가 Provider 계약, Job lifecycle과 Artifact 계보를 검증할 실행 가능한 기반이 필요합니다. 실제 모델을 임시로 연결하면 권리·성능·GPU 근거가 없는 값을 계약 사실로 만들 위험이 있습니다.

## 결정

Python 3.11 이상과 FastAPI·Pydantic으로 다음 계층을 구현합니다.

```text
Provider API
→ JobApplicationService
→ AudioProvider capability interface
→ FakeAudioProvider
→ in-memory Job / Artifact / Model Manifest registry
```

REST 경로는 DohaMusic 목표 계약의 `/api/v1/providers/{provider_id}` 매핑을 사용하고 `provider_id`는 `audio`, `api_contract_version`은 `1.0`으로 고정합니다. `CreateJob`은 비동기 의미를 보존해 `queued` Job을 만들며 Foundation에는 자동 worker를 두지 않습니다. 테스트와 embedding consumer가 명시적으로 `run_job`을 호출합니다.

Fake Provider는 Music Generation, Stem Separation과 Audio Analysis의 deterministic Metadata만 생성합니다. 실제 음원, 모델, Checkpoint, Dataset과 외부 Provider를 읽거나 호출하지 않습니다. Persistence는 repository abstraction과 in-memory 구현만 두며 DB·migration·분산 queue를 도입하지 않습니다.

## 계약 의미

- 상태는 `queued → running → succeeded|failed|cancelled`와 `queued → cancelled`만 허용합니다.
- Retry는 원본 상태·오류를 보존하고 새 Job ID와 `retry_of_job_id`를 사용합니다.
- Idempotency fingerprint는 idempotency key를 제외한 canonical CreateJob request 전체입니다.
- Artifact와 게시된 Manifest는 같은 identity로 변경할 수 없습니다.
- `progress_percent=100`만으로 성공하지 않으며 Artifact 등록 후 `succeeded`를 확정합니다.
- queued·running 취소는 worker가 없는 Fake Runtime에서 즉시 최종 `cancelled`가 됩니다.

## 선택 이유

공통 계약을 실제 모델 환경과 분리해 빠르게 반복 검증할 수 있고, 향후 Fake Provider만 승인된 Real Provider Adapter로 교체할 수 있습니다. FastAPI는 DohaMusic의 목표 REST mapping과 contract test를 직접 표현하기 위해 사용하고 Pydantic은 요청·Manifest·Artifact validation에 사용합니다.

## 대안

1. 실제 모델부터 연결: Dataset·Checkpoint·권리와 GPU 검증이 없어 제외합니다.
2. DB와 외부 Queue를 먼저 도입: 현재 계약 검증 범위를 넘고 persistence authority가 없어 제외합니다.
3. Provider가 다음 Provider를 호출: DohaMusic orchestration 경계를 위반하므로 금지합니다.

## 영향과 후속 작업

실제 Runtime Adapter는 동일 `AudioProvider` interface를 구현해야 합니다. 영속 Job repository, worker, 인증, Artifact resolver, 실제 Model Manifest 승인, GPU 실행과 DohaMusic 통합은 별도 PR에서 결정하고 검증합니다.

## 재검토 조건

- 첫 실제 모델 Adapter와 Checkpoint를 승인할 때
- 영속 DB·Queue·worker 또는 Provider 인증을 도입할 때
- 공통 contract major version이나 Artifact URI 정책이 변경될 때
