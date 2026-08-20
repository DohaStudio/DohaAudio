# Reviewer Authority Registry와 Human Semantic Review Workflow

> 문서 상태: governance Foundation [구현]
> 실제 reviewer authentication·authority 등록·semantic approval: [미구현]

## 경계

이 Foundation은 `SemanticRoleEvidence`를 사람이 검토할 때 필요한 domain authorization과 감사 계보를 정의합니다. 실제 계정 인증, reviewer 지정, Music·Traditional 승인 또는 거절은 수행하지 않습니다. Repository에 등록되는 reviewer identity는 `reviewer-test/...` 같은 opaque logical ID이며 이메일·계정 profile·private note를 저장하지 않습니다.

```text
SemanticRoleEvidence
  → SemanticReviewRequest
  → ReviewerAuthorityRegistry
  → HumanSemanticReviewDecision
  → current authority/evidence revalidation
  → CandidateRoleDispositionPolicy
```

Reviewer authorization은 identity authentication이 아닙니다. 현재 실제 인증 adapter가 없으므로 production human approval workflow는 운영상 비활성화되어 있습니다.

## Reviewer authority

`ReviewerAuthority`는 authority ID/version, opaque reviewer ID, candidate, structural role, proposed semantic role, evidence-policy/role-policy identity, approve/reject action, effective/expiry와 감사 reason code를 가진 불변 레코드입니다. Wildcard scope는 제공하지 않습니다.

`ReviewerAuthorityRegistry`는 같은 ID/version의 canonical replay만 idempotent하게 허용하고 다른 content overwrite를 거부합니다. Future-effective, expired, pre-revoked 또는 별도 revocation record가 유효한 authority는 decision 생성과 downstream 소비에서 fail-closed합니다.

Revocation은 기존 authority나 decision을 삭제하지 않습니다. 과거 decision은 감사 history로 남지만, 현재 role-policy 소비 시 authority를 다시 조회하므로 revocation 이후에는 재검토가 필요합니다.

## Review request

`SemanticReviewRequest`는 candidate·role, evidence·membership fingerprint와 sampling·path·companion·role·evidence policy identity를 canonical request ID에 결합합니다. 새 request는 항상 `pending`입니다. `approved`, `rejected`, `cancelled`, `superseded`는 별도 immutable resolution record로 표현되어 원본 request를 변경하지 않습니다. Evidence 또는 policy가 변경되면 새 request를 만들고 기존 pending request를 supersede해야 합니다.

## Human decision

`HumanSemanticReviewDecision`은 request ID, authority ID/version, opaque reviewer ID, approve/reject outcome, 전체 evidence/policy binding, safe reason code와 결정 시각을 canonical decision ID에 포함합니다. 한 request에는 하나의 terminal decision만 허용하며 동일 decision replay만 idempotent합니다.

Decision 제출 시 request pending 상태, current evidence, 모든 policy identity, evidence-policy allowlist, authority identity/version/scope/action/time과 evidence sufficiency를 검증합니다. Rejected decision은 기존 role disposition에서 `blocked`로 소비되어 silent retry되지 않습니다. Approved decision은 semantic disposition만 해결하며 Rights, Integrity, Split 또는 Training Gate를 변경하지 않습니다.

## 소비와 실제 상태

`HumanSemanticReviewWorkflow.apply_to_role_policy()`는 모든 role의 request·decision·현재 evidence·policy와 authority 상태를 다시 검증한 뒤 기존 PR #11 role-policy 적용 함수에 전달합니다. Authority가 나중에 revoke되거나 evidence/policy가 바뀌면 과거 decision의 현재 소비는 차단됩니다.

테스트에는 `reviewer-authority/reviewer-test/...` namespace의 synthetic authority만 존재합니다. 실제 Music·Traditional authority와 human approval은 0개입니다.

| candidate | semantic decisions | inventory ready |
|---|---|---|
| Music loop | audio/MIDI/JSON `review_required` | `false` |
| Traditional music | audio/MIDI/JSON `review_required`; unresolved group 32 | `false` |

`RIGHTS_GATE_PASS`, `DATASET_INTEGRITY_PASS`, `DATASET_SPLIT_FROZEN`과 모든 Training Gate는 계속 `false`입니다.
