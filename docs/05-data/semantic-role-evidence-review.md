# Semantic Role Evidence Review

> 문서 상태: bounded evidence·review Foundation [구현]
> 실제 semantic role approval·Rights·Integrity·Enrollment·Training: [미수행]

## 경계

`SemanticRoleEvidence`는 `audio_member`, `midi_member`, `json_member`, `other_member`라는 structural role을 변경하지 않습니다. 관찰 evidence와 `SemanticRoleReviewDecision`을 별도 불변 계약으로 유지하며, automated analysis는 human approval을 대신하지 않습니다.

Evidence는 candidate ID, sampling plan ID·version, path policy ID·version·membership fingerprint, companion policy ID·version과 role policy ID·version에 결합됩니다. 다른 candidate, membership 또는 policy에 재사용하면 fail-closed합니다. 동일 evidence ID에 다른 summary를 게시할 수 없습니다.

가능한 review vocabulary는 `primary_audio_candidate`, `conditioning_candidate`, `symbolic_companion_candidate`, `metadata_candidate`, `annotation_candidate`, `unsupported`, `unknown`입니다. 이는 제안 상태이며 실제 role disposition으로 반영하려면 충분한 evidence와 policy에 등록된 reviewer authority의 exact human review가 모두 필요합니다.

## Sampling plan

`RoleEvidenceSamplingPlan`은 candidate, structural role, plan identity/version, requested sample count, selection key, coverage dimension과 byte ceiling을 명시합니다. 현재 strategy는 `deterministic_archive_coverage`입니다. archive logical ID를 deterministic hash 순서로 배열한 뒤 archive마다 opaque member identity 순서로 round-robin 선택합니다.

따라서 동일 membership과 동일 plan은 filesystem enumeration 순서와 무관하게 동일 subset을 만듭니다. 요청 수가 population보다 크면 population에서 안전하게 멈추며 empty population을 전체 Dataset으로 오인하지 않습니다. 실제 approval에 필요한 production sample size는 이 Foundation에서 선언하지 않습니다.

## Sanitized observation

JSON probe는 선택된 member만 caller ceiling까지 읽습니다. raw value와 raw key를 evidence에 저장하지 않고 다음 집계만 보존합니다.

- top-level JSON type count
- raw value를 제거한 nested schema-shape fingerprint
- unique/dominant/mismatch schema count
- `dataset_like`, `annotation_like`, `reference_like` 고정 category의 document presence count

MIDI probe는 선택된 member의 첫 14-byte SMF header만 읽습니다. format, track count, division과 이 세 값의 structural signature count만 보존합니다. note sequence와 나머지 MIDI content는 읽거나 저장하지 않습니다.

WAV header는 audio member의 semantic Training 의미를 입증하지 않으므로 실제 probe를 수행하지 않았습니다. Audio evidence는 membership-only이며 decode count는 0입니다.

## 실제 bounded 결과

두 candidate 모두 JSON 32개와 MIDI 32개를 deterministic archive-coverage plan으로 관찰했습니다. 이는 전체 content parse나 production sufficiency threshold가 아닙니다.

| candidate | JSON population | sampled | valid | unique schema | dominant | mismatch | top-level |
|---|---:|---:|---:|---:|---:|---:|---|
| Music loop | 108,000 | 32 | 32 | 2 | 22 | 10 | object 32 |
| Traditional music | 9,961 | 32 | 32 | 3 | 12 | 20 | object 32 |

Music JSON 32개에는 `dataset_like` category가 모두 관찰됐습니다. Traditional JSON 32개에는 `dataset_like`, `annotation_like`, `reference_like` category가 모두 관찰됐습니다. Category는 key pattern의 sanitized count일 뿐 raw key·value나 semantic approval이 아닙니다.

| candidate | MIDI population | sampled | valid | format | tracks | division | signatures |
|---|---:|---:|---:|---|---|---|---:|
| Music loop | 108,000 | 32 | 32 | 1: 32 | 2: 32 | 120: 29, 480: 3 | 2 |
| Traditional music | 9,961 | 32 | 32 | 0: 28, 1: 4 | 1: 28, 2: 1, 3: 3 | 480: 32 | 3 |

WAV population은 Music 108,000, Traditional 9,961이지만 sampled header와 decode는 모두 0입니다. Source aggregate는 Music 108,000 groups, Traditional 9,977 groups와 9,945 complete·32 partial/orphan 상태를 그대로 보존합니다.

## Review와 role policy 연결

`SemanticRoleEvidencePolicy`는 required observation kind, minimum sample count, completeness와 선택적 schema consistency ceiling을 caller-configurable하게 표현합니다. `allow_automatic_approval=true`는 계약에서 거부합니다. 실제 두 candidate policy에는 승인된 reviewer authority가 없습니다.

따라서 Music과 Traditional의 audio, MIDI, JSON decision은 모두 `review_required`이고 automatic approval은 0입니다. Synthetic test에서만 등록된 test reviewer authority와 exact evidence를 사용해 approved decision을 만들고 기존 `CandidateRoleDispositionPolicy`가 이를 소비할 수 있음을 검증합니다.

| candidate | structural ready | semantic decisions | inventory ready |
|---|---|---|---|
| Music loop | `true` | audio/MIDI/JSON `review_required` | `false` |
| Traditional music | `false` | audio/MIDI/JSON `review_required` | `false` |

Traditional의 MIDI+WAV 16개와 JSON-only 16개는 계속 group-level `review_required`입니다. Bounded semantic evidence는 partial group을 자동 포함·제외하거나 source를 변경하지 않습니다.

## 독립 Gate

- `RIGHTS_GATE_PASS=false`
- `DATASET_INTEGRITY_PASS=false`
- `DATASET_SPLIT_FROZEN=false`
- `MODEL_SELECTED=false`
- `TRAINING_CONFIG_VALID=false`
- `ENVIRONMENT_PREFLIGHT_PASS=false`
- `TRAINING_PREFLIGHT_PASS=false`
- `TRAINING_EXECUTION_READY=false`
- `TRAINING_APPROVAL_CONSUMED=false`

Observed schema ≠ semantic meaning, MIDI structure ≠ supervision role, audio member ≠ Training target, representative sample ≠ whole-Dataset proof, automated suggestion ≠ human approval입니다.
