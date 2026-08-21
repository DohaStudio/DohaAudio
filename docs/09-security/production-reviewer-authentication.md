# Production Reviewer Authentication Selection

> 문서 상태: provider model selection·provider-neutral contract [구현]
> Configuration·실제 검증·private store·reviewer 운영: [미구현]

## Authority와 historical decision

- DohaAudio는 사용자를 직접 소유하지 않는 독립 Provider이며 DohaMusic만 호출합니다.
- 사용자 권한과 최종 Workspace 상태는 DohaMusic 책임입니다.
- DohaMusic V1은 local-only이고 일반 product login 없이 single owner/operator reviewer authentication을 요구합니다.
- Upstream identity는 `LOCAL_AUTHENTICATED_OPERATOR`, proof model은 `OS_BOUND_LOCAL_OPERATOR_CREDENTIAL`이며 concrete OS adapter는 미구현입니다.
- DohaLM은 cloud deployment가 범위 밖이고 authentication이 없으며, DohaVocal과 공통 저장소에도 production identity convention이 없습니다.

ADR-014는 product authority가 없던 당시 provider를 선택하지 않은 올바른 historical fail-closed decision입니다. DohaMusic PR #109와 ADR-038이 V1 topology·reviewer·identity·network·assurance를 확정해 provider-selection blocker를 해결했고 ADR-015가 selection state만 대체합니다.

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

Local Operator는 upstream human identity model로 선택됐지만 “같은 PC”, localhost, process owner 또는 OS username을 proof로 사용할 수 없습니다. OIDC와 GitHub Identity는 V1 external identity provider로 선택하지 않았습니다. DohaAudio downstream model은 external vendor IdP가 아닌 `DOHAMUSIC_DELEGATED_ASSERTION`입니다.

## 결정과 상태

현재 decision version은 `auth-provider-selection/v2`입니다. DohaMusic ADR-038 authority에 따라 `AUTH_PROVIDER_SELECTED=true`, `SELECTED_AUTHENTICATION_PROVIDER_MODEL=DOHAMUSIC_DELEGATED_ASSERTION`, `SELECTED_EXTERNAL_IDENTITY_PROVIDER=null`입니다. Provider model 선택, config 존재, adapter operational, private mapping 존재, authority 부여와 human review 활성화는 각각 독립 상태입니다.

```text
provider type selected
!= provider configured
!= adapter operational
!= reviewer mapped
!= ReviewerAuthority granted
!= human review enabled
```

현재 실제 상태는 `AUTH_PROVIDER_CONFIGURED=false`, `AUTH_PROVIDER_OPERATIONAL=false`, `PRIVATE_IDENTITY_STORE_OPERATIONAL=false`, real mapping·authority·approval 모두 0입니다. Current selection을 config 없이 bootstrap하면 `AUTH_PROVIDER_NOT_CONFIGURED`로 fail-closed합니다.

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

## 구현 계약

`AuthenticationProviderSelection`은 versioned selection 또는 unresolved requirements를 기록합니다. Historical v1 record는 보존하고 current v2 record는 `dohamusic/adr-038` authority reference, external IdP null과 immutable `DohaMusicDelegatedAssertionPolicy`를 포함합니다. Policy는 issuer owner DohaMusic, audience DohaAudio, `SHORT_LIVED`, freshness·expiry·replay resistance required, external auth network false, offline capable true와 upstream MFA false를 exact하게 검증합니다.

`ProductionAuthenticationProviderConfig`는 provider ID/type, expected issuer/audience, algorithm allowlist, freshness/clock policy, network·replay requirement와 explicit `enabled`만 포함합니다. Delegated model의 synthetic contract config도 issuer/audience exact match, external network false, replay required와 empty algorithm list를 강제합니다. Assertion format·crypto algorithm·exact TTL은 미선택입니다. Pydantic extra-field 차단 때문에 token, password, key, assertion, client secret 같은 값을 config에 추가할 수 없습니다.

`AuthenticationProviderFactory`는 다음을 fail-closed합니다.

- historical/pending selection → `AUTH_PROVIDER_NOT_SELECTED`
- config 없음 → `AUTH_PROVIDER_NOT_CONFIGURED`
- disabled config → `AUTH_PROVIDER_DISABLED`
- selection/config 불일치 → `AUTH_PROVIDER_SELECTION_MISMATCH`
- fake production 사용 → `AUTH_PROVIDER_FAKE_FORBIDDEN`
- unknown provider enum → configuration validation 실패

명시적 synthetic delegated selection과 valid config가 있어도 현재 factory는 `UnavailableProductionAuthenticationProvider`만 만듭니다. 이 stub은 `operational=false`이며 `verify()`와 `revalidate()`에서 `AUTH_PROVIDER_NOT_OPERATIONAL`만 반환하고 `VerifiedAuthenticationContext`를 절대 발급하지 않습니다. Local Operator, OIDC, GitHub Identity, 기본 provider와 fake fallback은 없습니다.

향후 real delegated adapter는 기존 `AuthenticationProvider`를 구현하고 `AuthenticationCredentialReference`를 ephemeral input, 기존 `VerifiedAuthenticationContext`를 유일한 trusted output으로 사용합니다. 서명·authenticity, exact issuer/audience, subject, expiry/not-before, clock/freshness, replay resistance와 assurance를 검증해야 합니다. Raw assertion과 credential은 장기 저장하지 않습니다.

V1 selected architecture는 external IdP network 없이 offline-capable해야 합니다. Same-machine DohaMusic↔DohaAudio transport는 external authentication network와 별도입니다. Assertion transport·format·algorithm, exact TTL, replay cache, key storage·rotation과 bounded retry는 real adapter PR 전 별도 계약으로 정합니다. Authentication failure는 application이 무한 재시도하지 않습니다.

## Secret과 private identity store

`SecretResolver`는 private composition boundary뿐이며 구현과 secret reference도 이번 단계에 없습니다. 실제 signing/verification key, secret, `.env`, token, assertion 생성·저장·조회는 0입니다.

`ReviewerIdentityMappingStore`는 기존 register/get/revoke/resolve/current-check semantics를 persistent implementation이 제공하기 위한 protocol입니다. 기존 `ReviewerIdentityMappingRegistry`가 synthetic in-memory implementation으로 이 protocol을 만족합니다. 한 mutation은 부분 mapping·revocation을 남기지 않도록 implementation transaction owner가 atomic하게 처리해야 합니다.

Private store에는 provider/issuer/private subject reference와 opaque reviewer mapping만 둡니다. Public semantic DB와 `ReviewerAuthorityRegistry`에는 provider subject를 넣지 않습니다. 실제 encryption-at-rest와 DB는 deployment threat model 뒤에 결정합니다. Provider migration은 old mapping의 explicit revoke/supersede와 new principal mapping의 explicit provisioning으로 수행하며 opaque reviewer ID와 authority를 provider-specific account에 직접 결합하지 않습니다.

## 미구현과 운영 차단

실제 local OS credential 검증, assertion signing·verification, OAuth/OIDC/JWKS/GitHub API, replay cache, secret store, persistent private DB, identity mapping provisioning, authority provisioning과 semantic decision은 구현하지 않았습니다. Production human review는 계속 비활성화됩니다. Authentication selection은 Rights·Integrity·Split·Model·Config·Environment·Training Gate를 변경하지 않습니다.
