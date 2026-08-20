# 학습 전략

> 문서 상태: Training 계약·preflight·dry-run [구현]
> 실제 Training·Fine-tuning: [미구현]

Training은 DohaAudio 책임이며 DohaMusic Runtime과 분리된 환경에서 수행합니다. 대규모 기반 모델의 직접 사전학습은 현재 확정 범위가 아닙니다.

## 계획된 단계

```text
승인된 Dataset Manifest
→ 고정 Split
→ 전처리 계약 검증
→ Training / Fine-tuning Run
→ Checkpoint
→ Evaluation
→ 승인된 Model Manifest
```

각 Run은 Dataset Manifest ID, 설정 checksum, 코드 revision, Runtime environment, seed, 시작·종료 상태와 출력 Artifact ID를 기록해야 합니다. 실패·취소 Run을 성공으로 표시하지 않습니다.

Checkpoint와 log는 `DohaArtifacts/audio`에 저장하며 Git에 포함하지 않습니다. 구체적인 Framework, 모델과 GPU 요구량은 Research 및 실제 검증 후 결정합니다.

## Pre-Training Readiness 구현

`TrainingConfig`는 model·Dataset identity, 요구 capability·input/output format, batch, learning rate, 단일 epoch/step limit, seed, precision, logical checkpoint policy, evaluation cadence와 resource constraint를 불변 snapshot으로 검증합니다. 값은 모두 caller가 명시하며 VRAM·batch·learning rate를 production 권장값으로 제공하지 않습니다.

`TrainingReadinessService`는 Dataset integrity, license, `training_allowed`, evidence review·effective·expiry, Model Manifest provider/capability/input format/output format/contract version과 logical output policy를 fail-closed로 검증합니다. 실패 시 `BLOCKED`와 reason code를 반환합니다.

Dry-run은 canonical config fingerprint와 deterministic planned `TrainingRun` identity만 계산합니다. DB·Artifact mutation, Dataset decode, model load, optimizer 생성·step, gradient, CUDA allocation과 Checkpoint write는 모두 0입니다. planned Run은 `started_at=null`, `optimizer_step=0`, output Checkpoint ID 없음 상태입니다.

`PRE_TRAINING_READY=true`는 fixture 기반 코드·계약 Gate가 Training 직전 상태라는 뜻입니다. 실제 Dataset 법률 승인, Training 실행 승인, GPU 검증, 성능 또는 상업 이용 승인을 뜻하지 않습니다.

## Training Admission

`TrainingAdmissionService`는 `DATASET_AUTHORITY_VALID`, `RIGHTS_GATE_PASS`, `DATASET_INTEGRITY_PASS`, `DATASET_SPLIT_FROZEN`, `MODEL_SELECTED`, `TRAINING_CONFIG_VALID`, `ENVIRONMENT_PREFLIGHT_PASS`, `TRAINING_PREFLIGHT_PASS`, `TRAINING_EXECUTION_READY`를 별도 boolean으로 반환합니다. execution ready는 모든 Gate와 별도 실행 승인이 참일 때만 가능합니다.

현재 실제 후보 조사에서는 권리 승인 Dataset Manifest, Music Generation training model/framework와 authoritative TrainingConfig가 없으므로 `TRAINING_EXECUTION_READY=false`입니다. 확인된 GPU 정보는 환경 inventory일 뿐 compatibility·VRAM 권장값 또는 실행 승인을 의미하지 않습니다. `TRAINING_APPROVAL_CONSUMED=false`, optimizer step·Checkpoint·GPU allocation·Evaluation execution은 모두 0입니다.

Semantic role evidence와 review decision은 Training Admission 이전의 local 검토 계약입니다. Semantic role이 human-approved 상태가 되더라도 Rights·Integrity·Split·Model·Config·Environment·Execution Gate를 변경하지 않습니다. 현재 실제 candidate는 reviewer authority가 없으므로 모든 role이 `review_required`입니다.

Human review workflow의 authority·request·decision lineage도 semantic disposition에만 영향을 줍니다. Reviewer authority 등록이나 semantic approval은 Rights evidence, full checksum, DatasetVersion, split 또는 explicit Training approval을 대체하지 않습니다.

Rights Enrollment는 Training 이전의 별도 단계입니다. `DatasetEnrollmentService`가 Manifest·DatasetVersion·Split을 등록하더라도 model, TrainingConfig, environment, preflight와 explicit execution approval Gate를 자동 승인하지 않습니다. 현재 실제 후보에서 발급된 Manifest·Version·Split은 0개입니다.
