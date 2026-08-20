# ADR-010: Candidate Role Disposition과 Partial Companion Policy

## 상태

Accepted — 2026-08-20

## 배경

PR #9는 Music loop의 108,000개 complete group과 Traditional music의 9,945개 complete·32개 partial group을 path-free하게 식별했습니다. 그러나 relationship completeness만으로 JSON·MIDI·WAV의 Training 의미나 incomplete group의 include/exclude 결정을 내릴 근거는 없습니다. 구조적 포함과 의미적 사용을 같은 disposition으로 처리하면 complete group을 Training 승인으로 오인하거나 partial group을 silently skip할 위험이 있습니다.

## 결정

1. `CandidateRoleDispositionPolicy`를 candidate, path policy ID·version·evidence fingerprint, companion policy ID·version에 결합합니다.
2. Group의 구조적 disposition `structural_include`, `exclude`, `blocked`, `review_required`와 role의 semantic `CompanionDisposition`을 분리합니다.
3. Complete group은 candidate별 명시 정책에서 structural candidate로 포함할 수 있지만 Training semantic 의미를 자동 부여하지 않습니다.
4. Partial과 orphan은 silent include할 수 없습니다. 명시 정책에 따른 exclusion은 complete-only view에서 허용할 수 있으나 source 삭제가 아니며 source·included·excluded count를 모두 보존합니다.
5. Duplicate role, unsafe path와 unsupported role은 policy와 무관하게 fail-closed합니다.
6. Music과 Traditional 실제 policy는 complete를 structural include하고 partial/orphan과 모든 semantic role을 review-required로 유지합니다.
7. `inventory_ready`는 structural group policy와 semantic role policy가 해결된 DatasetInventory 후보 상태일 뿐 Rights·Integrity·Manifest·DatasetVersion·split·Training Gate를 변경하지 않습니다.
8. Decision contract와 reason에는 opaque identity와 safe code만 포함하고 raw filename, local path와 source content를 포함하지 않습니다.

## 결과

Music은 108,000개 group이 모두 structural include되어 `structural_candidate_ready=true`지만 role review 때문에 `inventory_ready=false`입니다. Traditional은 9,945개 complete group을 structural include하고 32개 partial/orphan을 review-required로 유지하므로 두 readiness가 모두 false입니다. 실제 exclusion, source mutation, checksum, Rights approval, Dataset enrollment와 Training은 수행하지 않습니다.
