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
