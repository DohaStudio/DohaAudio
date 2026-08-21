# ADR-015: DohaMusic Delegated Reviewer Assertion Provider Selection

## 상태

Accepted decision — implementation pending — 2026-08-21

## 배경

[ADR-014](ADR-014-production-reviewer-authentication-provider-selection.md)는 당시 repository evidence만으로 production topology, reviewer population, issuer와 assurance를 확정할 수 없어 provider를 선택하지 않았다. 그 no-selection은 product authority가 unresolved였을 때의 올바른 fail-closed historical decision이다.

이후 DohaMusic PR #109와 DohaMusic ADR-038이 V1 product authority를 확정했다. V1은 local-only, no general product login, single owner/operator와 local governance UI를 사용한다. DohaMusic은 upstream human identity를 `LOCAL_AUTHENTICATED_OPERATOR`와 `OS_BOUND_LOCAL_OPERATOR_CREDENTIAL`로 검증하고, DohaAudio는 downstream에서 delegated assertion을 검증한 뒤 private mapping과 별도 `ReviewerAuthority`를 적용한다.

## 결정

1. ADR-014의 provider-selection state만 이 ADR로 대체한다. ADR-014의 provider-neutral contract와 fail-closed 경계는 유지한다.
2. `AUTH_PROVIDER_SELECTED=true`로 전환한다.
3. `SELECTED_AUTHENTICATION_PROVIDER_MODEL=DOHAMUSIC_DELEGATED_ASSERTION`으로 정한다.
4. `SELECTED_EXTERNAL_IDENTITY_PROVIDER=null`로 정한다. OIDC와 GitHub Identity는 V1에서 선택하지 않는다.
5. Selection authority는 `dohamusic/adr-038`이며 runtime object가 GitHub SHA에 의존하지 않는다.
6. Upstream human identity model은 `LOCAL_AUTHENTICATED_OPERATOR`, proof model은 `OS_BOUND_LOCAL_OPERATOR_CREDENTIAL`이다. Concrete OS adapter는 선택하거나 구현하지 않는다.
7. Future assertion issuer owner는 exact `DohaMusic`, audience는 exact `DohaAudio`다.
8. Assertion은 `SHORT_LIVED`이고 freshness·expiry와 replay resistance를 반드시 검증한다. Exact TTL은 선택하지 않는다.
9. V1 reviewer authentication은 external authentication network를 요구하지 않고 offline-capable해야 한다. MFA는 V1 upstream requirement가 아니다.
10. Service identity와 human reviewer assertion은 별도 principal·credential이다. Service credential은 reviewer proof가 아니다.
11. `LOCAL_PERSISTENT_PRIVATE_STORE` requirement는 유지하되 concrete SQLite, OS secure store 또는 hybrid 기술은 선택하지 않는다.
12. Existing `AuthenticationProvider`, `VerifiedAuthenticationContext`, `ReviewerIdentityMappingStore`, `ReviewerAuthorityRegistry`와 `HumanSemanticReviewWorkflow` 경계를 재사용한다.

## Selection, configuration과 operation

현재 상태는 다음과 같다.

```yaml
AUTH_PROVIDER_SELECTED: true
SELECTED_AUTHENTICATION_PROVIDER_MODEL: DOHAMUSIC_DELEGATED_ASSERTION
SELECTED_EXTERNAL_IDENTITY_PROVIDER: null
AUTH_PROVIDER_CONFIGURED: false
AUTH_PROVIDER_OPERATIONAL: false
PRIVATE_IDENTITY_STORE_OPERATIONAL: false
REAL_IDENTITY_MAPPING_COUNT: 0
REAL_REVIEWER_AUTHORITY_COUNT: 0
REAL_HUMAN_APPROVAL_COUNT: 0
```

Selection은 configuration이 아니고 configuration은 operation이 아니다. Current selection에 config를 제공하지 않으므로 factory는 `AUTH_PROVIDER_NOT_CONFIGURED`로 fail-closed한다. Synthetic delegated config를 사용하는 contract test에서도 factory는 `UnavailableProductionAuthenticationProvider`만 반환하며 `verify()`와 `revalidate()`는 `AUTH_PROVIDER_NOT_OPERATIONAL`로 실패한다.

## Assertion security contract

- issuer exact match: `DohaMusic`
- audience exact match: `DohaAudio`
- lifetime class: `SHORT_LIVED`; exact TTL unresolved
- issued-at/freshness와 expiry 검증 required
- replay resistance required; replay cache·nonce consumption 미구현
- assertion format unresolved
- crypto/signing algorithm unresolved
- signing key, verification key와 key rotation 0
- raw assertion, token, credential과 private subject 저장 금지
- fake, OIDC, GitHub Identity 또는 local implicit trust fallback 금지
- authentication 성공만으로 mapping, `ReviewerAuthority` 또는 semantic approval 생성 금지

## 대안

- **Generic OIDC**: V1 external IdP로 선택하지 않는다. Future remote/multi-user에서 재검토할 수 있다.
- **GitHub Identity**: source-control identity를 semantic reviewer identity로 사용하지 않는다.
- **Local Operator 직접 Provider**: upstream proof model이지만 DohaAudio downstream adapter model이 아니다.
- **Fake Provider**: test-only이며 production에서 계속 금지한다.

## 보안과 영향

Selected model을 enum과 immutable selection record로 표현하고 factory가 config absence, mismatch, fake와 unavailable adapter를 fail-closed한다. DohaMusic service principal과 human assertion principal을 분리하고 provider-specific mapping registry를 만들지 않는다.

Music과 Traditional semantic state, Rights·Integrity·Split·Model·TrainingConfig·Environment·Training Gate는 변경하지 않는다. 실제 mapping, `ReviewerAuthority`, approval, Dataset, Artifact, model, GPU와 Training side effect는 0이다.

## 미구현

- DohaMusic local operator authentication과 concrete OS adapter
- DohaMusic assertion issuer와 signing
- assertion format, algorithm, exact TTL과 key lifecycle
- DohaAudio assertion verification adapter와 replay cache
- local persistent private identity store implementation
- real `ReviewerIdentityMapping`과 `ReviewerAuthority` provisioning
- human semantic review와 Rights approval

## 다음 단계

이 Draft PR을 별도로 최종 검증한 뒤 Ready, same-head 재검증과 squash merge를 수행한다. 이후 실제 authentication implementation은 DohaMusic local operator foundation, issuer foundation, DohaAudio verification adapter와 private store를 각각 독립 PR로 진행한다.
