# ADR-012: Reviewer Authority Registry와 Human Semantic Review Workflow

## 상태

Accepted — 2026-08-20

## 배경

PR #11은 bounded semantic evidence와 human decision을 분리했지만 production reviewer identity, versioned scope, request lineage와 revocation 후 소비 정책은 구현하지 않았습니다. Evidence policy의 authority ID만으로는 authentication과 authorization을 구분하거나 stale request·폐기 authority를 downstream에서 재검증하기 어렵습니다.

## 결정

1. `ReviewerAuthority`는 opaque reviewer ID와 exact candidate·role·semantic-role·evidence-policy·role-policy·action scope를 가진 versioned immutable record로 둡니다.
2. Authority registry는 동일 ID/version overwrite를 금지하고 canonical replay만 허용합니다.
3. Effective 이전, expiry 이후와 revocation 이후에는 decision 생성과 현재 소비를 모두 차단합니다.
4. Revocation은 history 삭제가 아닙니다. 과거 decision은 감사 record로 남지만 downstream 소비는 현재 authority를 재검증하므로 새 review가 필요합니다.
5. Evidence에서 decision으로 직접 이동하지 않고 canonical `SemanticReviewRequest`를 생성합니다.
6. Request 원본은 변경하지 않으며 terminal 상태와 supersession은 별도 immutable resolution record로 남깁니다.
7. 한 request에는 하나의 approve/reject decision만 허용합니다. 다른 판단에는 새 superseding request가 필요합니다.
8. Decision은 request, authority ID/version, reviewer ID, evidence와 모든 policy identity, safe reason code와 시각에 결합합니다.
9. Role-policy 소비 시 request·decision·현재 evidence·policy와 authority 미폐기 상태를 다시 확인합니다.
10. Rejected semantic decision은 role disposition을 `blocked`로 만들며 자동 retry하지 않습니다.
11. Domain authority registry는 실제 계정 authentication을 제공하지 않습니다. 인증 adapter가 없으므로 production approval은 비활성화 상태입니다.
12. Semantic approval은 Rights·Integrity·Split·Enrollment·Training approval과 독립입니다.

## 결과

Synthetic fixture는 version, expiry, revocation, scope, stale request, forged payload와 role-policy integration을 검증할 수 있습니다. 실제 reviewer authority와 Music·Traditional human decision은 생성하지 않으므로 현재 여섯 semantic decision은 모두 `review_required`이고 두 candidate의 `inventory_ready`는 false입니다.
