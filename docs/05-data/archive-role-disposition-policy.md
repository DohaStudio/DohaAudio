# Archive Role Disposition과 Partial Group Policy

> 문서 상태: candidate-bound structural ingestion policy [구현]
> 실제 Rights·Integrity·Enrollment·Training: [차단·미수행]

## 경계

`CandidateRoleDispositionPolicy`는 PR #9의 interpreted membership과 companion relationship evidence를 candidate, path policy ID·version·fingerprint, companion policy ID·version에 정확히 결합합니다. 이 계층은 source archive를 수정하거나 member를 삭제하지 않고 opaque group identity와 structural role만 사용합니다.

Structural role은 `audio_member`, `midi_member`, `json_member`, `other_member`입니다. 이 분류는 WAV가 Training target이고 MIDI가 supervision이며 JSON이 label 또는 metadata-only라는 의미를 부여하지 않습니다. Semantic role은 기존 `CompanionDisposition`으로 별도 표현하며 현재 실제 두 candidate의 모든 role은 `review_required`입니다.

## Group disposition

| 상태 | 의미 |
|---|---|
| `structural_include` | 구조상 DatasetInventory 후보 view에 포함 가능 |
| `exclude` | 명시적 policy에 따라 view에서 제외하며 source 삭제가 아님 |
| `blocked` | path·duplicate·unsupported 등 안전 조건 때문에 차단 |
| `review_required` | 근거가 부족해 include 또는 exclude를 결정하지 않음 |

Partial과 orphan은 policy에서 `structural_include`로 설정할 수 없습니다. Complete-only view는 partial/orphan을 명시적으로 `exclude`한 별도 정책에서만 가능하며 source total, included, excluded count를 모두 보존합니다. 현재 실제 정책은 근거 없는 exclusion을 하지 않습니다.

## Candidate policy

| candidate | role policy | complete | partial | orphan | role semantic disposition |
|---|---|---|---|---|---|
| Music loop | `archive-role/aihub-098/structural-review/v1` `1.0.0` | `structural_include` | `review_required` | `review_required` | 모든 role `review_required` |
| Traditional music | `archive-role/aihub-209/structural-review/v1` `1.0.0` | `structural_include` | `review_required` | `review_required` | 모든 role `review_required` |

Music과 Traditional policy는 서로 다른 candidate·path evidence·companion policy에 결합되어 교차 적용할 수 없습니다. 계산 결과나 policy identity가 다르면 safe `ROLE_POLICY_*` code로 fail-closed하며 raw filename과 local path를 reason에 넣지 않습니다.

## 실제 decision

| candidate | source groups | complete | partial | orphan | duplicate | structural include | review required | blocked | excluded | structural candidate ready | inventory ready |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| Music loop | 108,000 | 108,000 | 0 | 0 | 0 | 108,000 | 0 | 0 | 0 | `true` | `false` |
| Traditional music | 9,977 | 9,945 | 32 | 16 | 0 | 9,945 | 32 | 0 | 0 | `false` | `false` |

Traditional의 32개 review group은 MIDI+WAV이며 JSON이 없는 16개와 JSON-only orphan 16개입니다. 이 결과는 9,945 complete subset을 보존하지만 전체 candidate가 complete라고 표시하지 않습니다. `9,945 × 3 + 16 × 2 + 16 × 1 = 29,883` invariant도 유지합니다.

## Readiness 의미

`structural_candidate_ready`는 path interpretation이 통과하고, 포함 group이 하나 이상이며, blocked/review-required group이 없다는 뜻입니다. `inventory_ready`는 여기에 semantic role policy까지 해결됐을 때만 true입니다. 현재 Music은 group 구조만 준비됐고 role semantic review가 남아 false입니다. Traditional은 group review와 role review가 모두 남아 false입니다.

이 계층의 `inventory_ready=true`도 실제 Dataset enrollment를 승인하지 않습니다. 다음은 별도 Gate이며 현재 모두 false 또는 미발급입니다.

- `RIGHTS_GATE_PASS=false`
- `DATASET_INTEGRITY_PASS=false`
- `DATASET_SPLIT_FROZEN=false`
- Dataset Manifest·DatasetVersion 미발급
- TrainingConfig·Training approval 미발급

Complete relationship ≠ Training semantics, partial exclusion ≠ source deletion, structural candidate ≠ Dataset enrollment, role disposition ≠ Rights approval입니다.
