# ADR-013: Authenticated Reviewer Identity Boundary

## 상태

Accepted — 2026-08-21

## 배경

ADR-012는 opaque reviewer ID와 versioned authority를 제공하지만 실제 authenticated principal과의 연결을 의도적으로 외부에 두었습니다. Caller-supplied reviewer ID를 production identity로 신뢰하거나 authentication 성공만으로 authority를 만들면 domain authorization을 우회하고 private provider identity를 장기 audit record에 노출할 수 있습니다.

## 결정

1. Provider-specific SDK와 분리된 `AuthenticationProvider` verification protocol을 사용합니다.
2. `AuthenticatedPrincipal`은 immutable sanitized private object이며 access/refresh/ID token, raw assertion, password와 secret을 보존하지 않습니다.
3. Plain/deserialized principal은 authentication proof가 아닙니다. Provider-issued `VerifiedAuthenticationContext`만 재검증 후 사용합니다.
4. Provider ID, issuer, audience, authenticated/expiry time과 optional caller-owned freshness policy를 exact하게 검증합니다.
5. Provider subject와 public opaque reviewer ID 사이에는 별도 private `ReviewerIdentityMapping`이 반드시 존재해야 합니다.
6. Mapping은 versioned immutable record이고 effective·expiry·revocation을 fail-closed로 적용합니다. Authentication 성공은 mapping을 자동 생성하지 않습니다.
7. Active principal rebinding에는 predecessor revocation과 새 version이 필요하며 서로 다른 principal의 reviewer-ID collision은 차단합니다. Multi-provider account linking은 후속 범위입니다.
8. Authentication-enabled workflow는 raw reviewer-ID submission을 차단하고 provider context → mapping → existing ReviewerAuthority exact scope 순으로 검증합니다.
9. Mapping과 ReviewerAuthority는 decision 소비 시 다시 검증하지만 과거 mapping·authority·decision history는 삭제하지 않습니다.
10. Semantic decision에는 provider subject, session 또는 authentication artifact를 추가하지 않고 기존 opaque reviewer/evidence/policy/authority lineage를 유지합니다.
11. Foundation은 deterministic fake provider만 제공합니다. 실제 OAuth/OIDC, secret, real mapping, real authority와 real approval은 구현하지 않습니다.
12. Authentication success는 semantic approval, Rights approval, Integrity PASS 또는 Training approval을 만들지 않습니다.

## 결과

Verified authentication, private identity mapping, opaque reviewer identity와 기존 governance 사이의 경계가 구현됩니다. 그러나 real provider·mapping·authority가 0이므로 production human review는 계속 operationally disabled입니다. Music·Traditional semantic role은 모두 `review_required`이고 Rights·Integrity·Split·Training Gate는 계속 false입니다.
