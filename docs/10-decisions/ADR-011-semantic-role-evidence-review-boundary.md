# ADR-011: Semantic Role Evidence Review와 승인 경계

## 상태

Accepted — 2026-08-20

## 배경

PR #10은 structural group과 semantic role을 분리했지만 실제 JSON·MIDI·WAV role은 모두 `review_required`로 남겼습니다. 기존 candidate별 JSON 3개와 MIDI header 3개 관찰은 role 의미를 승인하기에 부족하며, sample 관찰을 곧바로 Training semantic 또는 human approval로 해석하면 fail-open 위험이 있습니다.

## 결정

1. `RoleEvidenceSamplingPlan`, `SemanticRoleEvidence`, `SemanticRoleReviewDecision`을 별도 불변 계약으로 둡니다.
2. Sampling plan은 candidate·role·version·selection key·coverage dimension·byte ceiling을 명시하고 opaque archive/member identity로 deterministic subset을 선택합니다.
3. Evidence는 candidate membership fingerprint와 path·companion·role policy identity에 exact binding합니다. Membership 또는 policy가 바뀌면 새 evidence가 필요합니다.
4. JSON은 caller-bounded document의 raw value를 제거한 schema shape fingerprint와 고정 category count만 보존합니다. MIDI는 14-byte SMF header distribution만 보존합니다. raw filename·value·binary와 note sequence를 공개 contract에 넣지 않습니다.
5. WAV header는 semantic meaning을 추가로 증명하지 않으므로 실제 candidate probe와 decode를 수행하지 않습니다.
6. Evidence registry는 같은 evidence ID의 다른 record 게시를 거부합니다.
7. Automated analysis는 `approved`를 만들 수 없습니다. Approval 또는 rejection은 evidence policy에 등록된 reviewer authority, exact evidence와 proposed role이 모두 일치하는 human review가 있어야 합니다.
8. Human approval이 있더라도 evidence sufficiency가 fail-closed 조건을 통과하지 못하면 `blocked`입니다. Direct deserialization도 decision identity와 human authority field 불변식을 검증합니다.
9. Approved synthetic decision은 기존 role policy disposition으로 변환할 수 있지만 실제 candidate에는 reviewer authority를 등록하지 않아 모두 `review_required`를 유지합니다.
10. Semantic review는 Rights·Integrity·Manifest·DatasetVersion·Split·Training Gate와 독립이며 이를 변경하지 않습니다.

## 결과

Music과 Traditional에서 각각 JSON 32개와 MIDI header 32개만 bounded 관찰했습니다. Music JSON은 2개, Traditional JSON은 3개 schema shape가 관찰됐고 MIDI header도 candidate별 구조 분포가 달랐습니다. 이 관찰은 semantic meaning 또는 whole-Dataset consistency를 증명하지 않습니다.

실제 audio/MIDI/JSON decision은 모두 `review_required`, automatic approval은 0입니다. Music은 `structural_candidate_ready=true`, Traditional은 32 partial/orphan 때문에 false이며 두 candidate의 `inventory_ready`, Rights, Integrity, Split과 Training Gate는 모두 false입니다. Source archive mutation·extraction·WAV decode·full checksum·Dataset enrollment·Training은 수행하지 않았습니다.

