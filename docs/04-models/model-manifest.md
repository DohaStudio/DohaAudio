# Model Manifest 최소 계약

> 문서 상태: [계획]
> 공통 Model Registry: [미구현]

Model Manifest는 Runtime이 사용할 모델과 근거를 연결하는 이식 가능한 Metadata입니다. 로컬 절대 경로와 비밀정보는 저장하지 않습니다.

| 필드 | 의미 | 필수 |
|---|---|---:|
| `provider_id` | Provider 식별자 | 예 |
| `model_id` | 모델 식별자 | 예 |
| `model_version` | 모델 논리 버전 | 예 |
| `checkpoint_version` | Checkpoint 버전 | 예 |
| `dataset_manifest_id` | 학습 Dataset Manifest 식별자 | 예 |
| `training_run_id` | Training Run 식별자 | 예 |
| `evaluation_result_id` | Evaluation 결과 식별자 | 예 |
| `license_status` | 코드·weight 라이선스 검토 상태 | 예 |
| `commercial_usage_status` | 상업 이용 검토 상태 | 예 |
| `recommended_vram` | 검증된 권장 VRAM | 예 |
| `artifact_checksum` | 모델 Artifact checksum | 예 |

구현 전 capability, 입력·출력 형식, API contract version, Runtime environment 필드의 공통 계약 포함 여부를 DohaMusic 및 다른 Provider와 확정해야 합니다.

## 상태 원칙

- 근거가 없으면 `UNKNOWN` 또는 `REVIEW_REQUIRED`를 사용합니다.
- 실제 측정 없이 VRAM 숫자를 작성하지 않습니다.
- License 확인과 상업 이용 승인을 동일한 상태로 취급하지 않습니다.
- Checkpoint 파일은 `DohaArtifacts/audio/checkpoints`에 두고 Manifest에는 Artifact ID와 checksum만 기록합니다.
