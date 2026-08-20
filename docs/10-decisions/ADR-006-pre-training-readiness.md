# ADR-006: 학습 전 Readiness Foundation

- 상태: 승인됨 [구현]
- 작성일: 2026-08-19
- 관련 명세: DohaStudio 공통 Job·Artifact·Model Manifest·Dataset Manifest 계약 `0.1.0`

## 배경과 문제

Runtime Foundation 이후 실제 Training을 시작하기 전에 process restart, 중복 worker, Dataset identity·split·권리, Training 설정과 출력 계보를 실패 안전하게 검증할 기반이 필요합니다. Production DB·실제 Dataset·모델을 조기에 연결하면 권리와 실행 승인이 없는 side effect가 발생할 수 있습니다.

## 결정

1. `JobRepository` protocol과 in-memory/SQLite 구현을 둡니다. SQLite 위치는 composition root에서 주입하고 단일 `jobs` aggregate table을 schema bootstrap합니다.
2. Job aggregate repository method가 짧은 transaction의 owner입니다. create/idempotency와 lifecycle payload를 atomic하게 저장합니다.
3. `ExecutionWorker`는 queued Job을 claim token·lease로 atomic claim합니다. Provider 실행 동안 DB transaction을 유지하지 않습니다.
4. stale running Job은 자동 재실행하지 않고 retryable `failed`로 복구합니다. 재실행은 새 Retry Job만 허용합니다.
5. `ArtifactResolver`는 Artifact ID와 내부 storage reference 해석을 분리하고 reference를 외부에 공개하지 않습니다.
6. 공통 Dataset Manifest 필드와 `train/validation/test` split, checksum·provenance·membership integrity, 불변 DatasetVersion을 구현합니다.
7. license, `training_allowed`, commercial usage와 redistribution을 분리하고 evidence가 누락·미검토·미발효·만료되면 fail-closed 합니다.
8. TrainingRun·TrainingConfig는 immutable snapshot이며 preflight와 dry-run만 구현합니다. Dry-run은 read-only이고 optimizer·GPU·Checkpoint side effect가 없습니다.
9. Evaluation은 future lineage metadata 계약만 준비하며 metric과 결과 Artifact를 만들지 않습니다.

## Recovery와 원자성

Queued Job은 restart 후 claim할 수 있습니다. Running lease 만료는 이전 Provider side effect를 알 수 없으므로 같은 row를 queued로 되돌리지 않습니다. `WORKER_LEASE_EXPIRED`로 실패 확정한 뒤 operator가 명시적 Retry를 생성합니다.

Artifact metadata는 batch 전체의 identity 충돌을 먼저 검증한 후 등록합니다. Provider failure나 cancellation을 관찰하면 정상 Artifact를 등록하지 않습니다. 실제 filesystem/DB를 아우르는 production completion UoW는 실제 Artifact 저장소 도입 시 별도 결정합니다.

## 선택 이유

SQLite는 Python 표준 라이브러리로 재현 가능한 local persistence를 제공하고 production DB authority를 추측하지 않습니다. Repository·worker·resolver protocol은 향후 persistence와 execution implementation을 교체할 수 있게 합니다. Dataset과 Training Gate는 실제 Payload를 읽지 않는 metadata fixture로 fail-closed 의미를 검증합니다.

## 금지와 미구현

- 실제 Dataset 다운로드·scan·decode
- 실제 모델 다운로드·load
- optimizer·gradient·GPU Training/Inference
- Checkpoint·Evaluation Artifact 생성
- background daemon·distributed queue·production DB
- 실제 법률·상업 이용 승인 생성
- DohaMusic·DohaLM·DohaVocal·`.github` 수정

## 재검토 조건

- production DB 또는 durable queue authority가 확정될 때
- 실제 Artifact filesystem completion UoW를 도입할 때
- 첫 실제 Dataset authority와 Training execution 승인을 연결할 때
- 공통 Dataset/Rights 계약 version이 변경될 때
