# ADR-014: Production Reviewer Authentication Provider Selection

## 상태

Accepted no-selection decision — 2026-08-21

## 배경

ADR-013은 provider-independent authentication과 private mapping 경계를 구현했지만 real provider는 선택하지 않았습니다. DohaAudio는 DohaMusic이 호출하는 독립 Provider이고 사용자 권한은 DohaMusic 책임입니다. 현재 DohaMusic은 local single-user 제한이며 공개 운영 인증·소유권은 미구현입니다. 운영 topology, reviewer population, browser/CLI 흐름, issuer owner, internet dependency, MFA·recovery·revocation 요구도 확정되지 않았습니다.

## 후보와 기준

Local authenticated operator, generic OIDC와 GitHub Identity를 security isolation, stable identity, issuer/audience, credential handling, revocation, MFA 확장, local development, production deployment, complexity, dependency, privacy, auditability와 portability 기준으로 비교했습니다.

- Local operator는 현재 local topology에 적합할 수 있지만 trusted OS credential, local secret 또는 reverse proxy 중 authority가 미정입니다. Implicit machine trust는 허용하지 않습니다.
- OIDC는 portable issuer/audience/subject 계약을 제공할 수 있지만 issuer·client·redirect·network·account lifecycle 요구가 없습니다.
- GitHub Identity는 source-control 사용 외 제품 reviewer identity 근거가 없고 vendor dependency와 private identity linkage가 추가됩니다.
- 자체 계정, mTLS 또는 trusted proxy도 deployment owner와 recovery 운영 근거가 없습니다.

## 결정

1. Provider를 임의 선택하지 않고 decision version `auth-provider-selection/v1`을 `PENDING_REQUIREMENTS`로 둡니다.
2. `AUTH_PROVIDER_SELECTED=false`이며 selection 전에는 config와 adapter를 활성화하지 않습니다.
3. 기존 `AuthenticationProvider`, `AuthenticationCredentialReference`, `AuthenticatedPrincipal`과 `VerifiedAuthenticationContext`를 재사용합니다.
4. Secret-free `ProductionAuthenticationProviderConfig`와 explicit enablement를 정의합니다. Unknown, missing, disabled, mismatch와 fake provider는 fail-closed합니다.
5. 현재 production adapter는 unavailable stub뿐이고 verified context를 만들지 않습니다.
6. Secret은 `SecretResolver` private boundary 밖으로 나오지 않으며 실제 구현·값은 추가하지 않습니다.
7. `ReviewerIdentityMappingStore` persistence protocol과 existing in-memory registry를 분리하되 public `ReviewerAuthorityRegistry`와 합치지 않습니다.
8. Selection, configuration, operational verification, private mapping, authority와 human review readiness를 독립 상태로 유지합니다.
9. Provider migration은 old principal mapping revoke/supersede와 new mapping explicit provisioning으로 수행합니다.
10. 이 결정은 common contract 변경을 요구하지 않습니다.

## 활성화 전 필수 결정

- local-only 유지 또는 remote/multi-user deployment topology
- identity issuer와 account lifecycle owner
- reviewer population과 onboarding/recovery/revocation 책임
- browser redirect 또는 CLI/service authentication 흐름
- internet dependency, outage와 network retry 정책
- audience, assurance/MFA, clock/freshness와 audit retention 정책
- secret manager와 private mapping store threat model

## 결과

Provider-neutral production contract와 fail-closed bootstrap을 synthetic test할 수 있지만 실제 login은 사용할 수 없습니다. 실제 secret·mapping·authority·approval은 0이고 production human review는 비활성화됩니다. Music·Traditional state와 Rights·Integrity·Training Gate는 변경되지 않습니다.
