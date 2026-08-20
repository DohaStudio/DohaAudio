# Authenticated Reviewer Identity Boundary

> 문서 상태: authentication Foundation [구현]
> 실제 OAuth/OIDC provider·identity mapping·ReviewerAuthority·human approval: [미구현]

Production provider 선택 상태와 fail-closed bootstrap은 [Production Reviewer Authentication](production-reviewer-authentication.md)을 따릅니다. 현재 provider 결정은 요구사항 부족으로 보류됐습니다.

## 경계

```text
AuthenticationCredentialReference (ephemeral, no secret)
  → AuthenticationProvider.verify()
  → provider-issued VerifiedAuthenticationContext
  → AuthenticatedReviewerResolver
  → private ReviewerIdentityMappingRegistry
  → opaque reviewer ID
  → existing ReviewerAuthorityRegistry
  → HumanSemanticReviewWorkflow
```

`AuthenticationProvider`는 provider-independent protocol입니다. `AuthenticatedPrincipal`은 provider ID, logical issuer·audience, private subject/session reference, authentication/expiry time, declared assurance·method와 verification status를 가진 immutable private object입니다. 이메일, username, display name, profile URL, phone, token, raw assertion 또는 secret을 포함하지 않습니다.

Principal object 자체는 authentication proof가 아닙니다. Provider가 발급하고 내부 witness와 issued-context identity를 다시 확인할 수 있는 `VerifiedAuthenticationContext`만 resolver가 수용합니다. Context가 복사·변조·직접 생성됐거나 principal이 future, expired, unverified, wrong provider·issuer·audience이면 fail-closed합니다. Optional maximum authentication age는 composition owner가 명시하며 Foundation이 production threshold를 추측하지 않습니다.

## Private identity mapping

`ReviewerIdentityMapping`은 `(provider_id, issuer_id, private subject_reference)`를 public-safe opaque `reviewer_id`에 결합하는 versioned immutable private record입니다. Mapping registry는 canonical replay만 idempotent하게 허용하고 동일 ID/version overwrite, active principal rebinding과 서로 다른 principal의 reviewer-ID collision을 차단합니다. Rebinding에는 predecessor의 explicit immutable revocation과 새 version이 필요합니다. 실제 multi-provider account linking은 구현하지 않습니다.

Unknown authenticated principal은 정상적인 `AUTHENTICATED but NOT_REGISTERED_REVIEWER` 상태이며 mapping을 자동 생성하지 않습니다. Future, expired, revoked mapping은 decision 생성과 기존 decision의 downstream 소비에서 모두 차단됩니다. Revocation은 mapping이나 과거 semantic decision을 삭제하지 않습니다.

## Workflow integration

Authentication resolver가 설정된 `HumanSemanticReviewWorkflow`는 caller가 reviewer ID를 직접 넘기는 기존 domain-only submission을 차단합니다. Authenticated path는 현재 provider context, mapping, evidence/policy와 기존 `ReviewerAuthorityRegistry` scope를 순서대로 검증합니다. Optional caller claim은 resolved reviewer ID와 일치하는지만 확인하며 identity source로 사용하지 않습니다.

Semantic decision은 기존 request, evidence, policy, authority와 opaque reviewer ID lineage만 유지합니다. Provider subject, session, verification context와 authentication metadata는 장기 semantic audit record에 복사하지 않습니다.

Authentication context는 decision 제출 시 검증하며 semantic decision에 보존하지 않습니다. 유효하게 생성된 decision은 context가 나중에 만료됐다는 이유만으로 소급 무효화하지 않고, downstream 소비 시 현재 private mapping과 ReviewerAuthority의 expiry·revocation을 다시 검증합니다. Expired context를 새 decision에 재사용하는 것은 차단됩니다.

## 현재 운영 상태

- 구현 provider: `FakeAuthenticationProvider` test fixture만 존재
- real network authentication/OAuth/OIDC exchange: 0
- production private identity mapping: 0
- real ReviewerAuthority: 0
- real semantic approvals/rejections: 0/0
- automatic approvals: 0
- production human review: operationally disabled
- Music·Traditional audio/MIDI/JSON: 모두 `review_required`
- Rights, Integrity, Split과 모든 Training Gate: `false`

Authentication은 authorization이 아닙니다. Authentication success는 reviewer registration이 아니며 reviewer registration은 ReviewerAuthority 또는 semantic approval이 아닙니다. Semantic approval도 Rights·Integrity·Training approval이 아닙니다.
