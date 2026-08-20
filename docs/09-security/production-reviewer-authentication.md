# Production Reviewer Authentication 설계 기반

> 문서 상태: provider-neutral production contract [구현]
> Provider 선택·설정·실제 검증·private store·reviewer 운영: [미구현]

## 조사된 운영 전제

- DohaAudio는 사용자를 직접 소유하지 않는 독립 Provider이며 DohaMusic만 호출합니다.
- 사용자 권한과 최종 Workspace 상태는 DohaMusic 책임입니다.
- DohaMusic의 현재 제품은 로컬 단일 사용자 제한이고 인증·소유권은 공개 운영 선행 조건입니다.
- 초기 구성은 한 개발 머신에 놓일 수 있지만 운영 topology, identity issuer, browser login, remote API와 account lifecycle은 확정되지 않았습니다.
- DohaLM은 cloud deployment가 범위 밖이고 authentication이 없으며, DohaVocal과 공통 저장소에도 production identity convention이 없습니다.

따라서 reviewer 수, single-user에서 multi-user로의 전환 방식, browser/CLI login, internet 의존 허용, issuer control, MFA, recovery, revocation owner를 저장소 근거만으로 확정할 수 없습니다.

## 후보 평가

| 기준 | Local authenticated operator | OIDC | GitHub Identity |
|---|---|---|---|
| 현재 local 개발 적합성 | 높음 | 별도 issuer 필요 | GitHub 의존 |
| remote/multi-user 확장 | 별도 설계 필요 | 표준 issuer·audience·subject로 확장 가능 | GitHub 계정에 결합 |
| issuer·audience 검증 | OS/프록시 경계를 먼저 정해야 함 | 명시적 계약 가능 | 제품 audience·검증 흐름을 별도 설계해야 함 |
| MFA·recovery·revocation | 선택한 local authority에 의존 | 선택한 issuer 정책에 의존 | GitHub 계정 정책에 의존 |
| privacy | 로컬에 제한 가능 | claims 최소화 필요 | 제품에 불필요한 GitHub linkage 위험 |
| network dependency | 경계에 따라 없음 | discovery/JWKS 또는 고정 key 운영 필요 | OAuth/API 의존 |
| 현재 근거 | trusted local credential 방식 미정 | issuer·client·deployment 미정 | source-control identity 외 제품 identity 근거 없음 |

Local Operator는 현재 topology와 가깝지만 “같은 PC”를 authentication proof로 사용할 수 없습니다. OIDC는 이식 가능한 후보지만 issuer, audience, browser redirect, nonce/state, key rotation과 account lifecycle 요구가 먼저 필요합니다. GitHub repository 사용은 product reviewer identity 선택 근거가 아니며 GitHub username이나 account ID도 opaque reviewer ID 또는 `ReviewerAuthority`가 아닙니다. 별도 자체 계정·mTLS·reverse proxy 후보도 owner와 운영 경계가 없어 추가 선택 근거가 없습니다.

## 결정과 상태

현재 결정은 `PENDING_REQUIREMENTS`이고 `AUTH_PROVIDER_SELECTED=false`입니다. Provider type 선택, config 존재, adapter operational, private mapping 존재, authority 부여와 human review 활성화는 각각 독립 상태입니다.

```text
provider type selected
!= provider configured
!= adapter operational
!= reviewer mapped
!= ReviewerAuthority granted
!= human review enabled
```

현재 실제 상태는 `AUTH_PROVIDER_CONFIGURED=false`, `AUTH_PROVIDER_OPERATIONAL=false`, `PRIVATE_IDENTITY_STORE_OPERATIONAL=false`, real mapping·authority·approval 모두 0입니다.

## 구현 계약

`AuthenticationProviderSelection`은 versioned selection 또는 unresolved requirements를 기록합니다. `ProductionAuthenticationProviderConfig`는 provider ID/type, expected issuer/audience, algorithm allowlist, freshness/clock policy, network requirement와 explicit `enabled`만 포함합니다. Pydantic extra-field 차단 때문에 token, password, key, client secret 같은 값은 config에 추가할 수 없습니다.

`AuthenticationProviderFactory`는 다음을 fail-closed합니다.

- selection 없음 → `AUTH_PROVIDER_NOT_SELECTED`
- config 없음 → `AUTH_PROVIDER_NOT_CONFIGURED`
- disabled config → `AUTH_PROVIDER_DISABLED`
- selection/config 불일치 → `AUTH_PROVIDER_SELECTION_MISMATCH`
- fake production 사용 → `AUTH_PROVIDER_FAKE_FORBIDDEN`
- unknown provider enum → configuration validation 실패

명시적 synthetic selection과 valid config가 있어도 현재 factory는 `UnavailableProductionAuthenticationProvider`만 만듭니다. 이 stub은 `operational=false`이며 `verify()`와 `revalidate()`에서 `AUTH_PROVIDER_NOT_OPERATIONAL`만 반환하고 `VerifiedAuthenticationContext`를 절대 발급하지 않습니다. 기본 provider와 fake fallback은 없습니다.

향후 real adapter는 기존 `AuthenticationProvider`를 구현하고 `AuthenticationCredentialReference`를 ephemeral input, 기존 `VerifiedAuthenticationContext`를 유일한 trusted output으로 사용합니다. 서명·authenticity, exact issuer/audience, subject, algorithm allowlist, expiry/not-before, clock/freshness와 assurance를 검증해야 합니다. Raw assertion과 credential은 장기 저장하지 않습니다.

Network client는 adapter 내부 별도 boundary이며 TLS, timeout과 bounded retry를 composition owner가 정합니다. Authentication failure는 application이 무한 재시도하지 않습니다. OIDC를 선택할 경우 discovery/JWKS cache, key rotation, nonce/state와 claims minimization을 real adapter PR에서 확정합니다.

## Secret과 private identity store

`SecretResolver`는 private composition boundary뿐이며 구현과 secret reference도 이번 단계에 없습니다. 실제 secret, `.env`, token, key 생성·저장·조회는 0입니다.

`ReviewerIdentityMappingStore`는 기존 register/get/revoke/resolve/current-check semantics를 persistent implementation이 제공하기 위한 protocol입니다. 기존 `ReviewerIdentityMappingRegistry`가 synthetic in-memory implementation으로 이 protocol을 만족합니다. 한 mutation은 부분 mapping·revocation을 남기지 않도록 implementation transaction owner가 atomic하게 처리해야 합니다.

Private store에는 provider/issuer/private subject reference와 opaque reviewer mapping만 둡니다. Public semantic DB와 `ReviewerAuthorityRegistry`에는 provider subject를 넣지 않습니다. 실제 encryption-at-rest와 DB는 deployment threat model 뒤에 결정합니다. Provider migration은 old mapping의 explicit revoke/supersede와 new principal mapping의 explicit provisioning으로 수행하며 opaque reviewer ID와 authority를 provider-specific account에 직접 결합하지 않습니다.

## 미구현과 운영 차단

실제 OAuth exchange, OIDC discovery/JWKS, GitHub API, local OS credential 검증, secret store, persistent private DB, identity mapping provisioning, authority provisioning과 semantic decision은 구현하지 않았습니다. Production human review는 계속 비활성화됩니다. Authentication 상태는 Rights·Integrity·Split·Model·Config·Environment·Training Gate를 변경하지 않습니다.
