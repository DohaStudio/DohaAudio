# DohaAudio 요구사항

> 문서 상태: [계획]
> 구현 상태: Runtime·Pre-Training Readiness 요구사항 [구현], 실제 AI·Dataset·Training [미구현]

## 기능 요구사항

| ID | 요구사항 | 상태 |
|---|---|---|
| FR-001 | DohaMusic이 Music Generation Job을 생성할 수 있어야 한다. | [계획] |
| FR-002 | Instrumental Generation capability를 제공해야 한다. | [계획] |
| FR-003 | 음원을 Stem으로 분리할 수 있어야 한다. | [계획] |
| FR-004 | BPM, Key와 Music Structure를 분석할 수 있어야 한다. | [계획] |
| FR-005 | Audio Quality Analysis 결과를 제공해야 한다. | [계획] |
| FR-006 | Dataset Pipeline이 raw, interim, processed, manifest, split, license를 구분해야 한다. | 계약·검증 [구현], 실제 Pipeline [미구현] |
| FR-007 | Training과 Fine-tuning Run을 재현 가능한 식별자로 기록해야 한다. | 계약·dry-run [구현], 실행 [미구현] |
| FR-008 | 모델별 Evaluation 결과와 Model Manifest를 연결해야 한다. | metadata 계약 [구현], 실행 [미구현] |
| FR-009 | Runtime 작업의 생성, 상태, 취소, 재시도와 오류를 표현해야 한다. | [구현] |
| FR-010 | Provider API 계약 버전을 명시해야 한다. | [구현] |
| FR-011 | 결과를 경로가 아닌 Asset/Artifact 식별자와 Metadata로 반환해야 한다. | [구현] |
| FR-012 | 다른 AI Provider를 직접 호출하지 않아야 한다. | [구현] |
| FR-013 | 주입된 Dataset authority를 read-only로 조사하고 경로를 공개 계약에 노출하지 않아야 한다. | [구현] |
| FR-014 | Dataset·rights·split·model·config·environment·execution admission을 독립 Gate로 판단해야 한다. | [구현] |
| FR-015 | 권리 evidence를 candidate·Manifest·evidence ID·scope에 결합하고 승인된 exact membership만 Dataset으로 등록해야 한다. | Gate [구현], 승인 Dataset [미확보] |
| FR-016 | archive member를 extract 없이 read-only로 조사하고 path·identity·encryption·nested archive·resource 위험을 차단해야 한다. | ZIP Foundation [구현], 실제 enrollment [차단] |
| FR-017 | generic archive path 보안을 유지하면서 evidence-bound candidate path를 가역적 logical identity로 해석하고 companion 관계를 path-free로 분류해야 한다. | Policy [구현], ingestion 의미 [검토 필요] |
| FR-018 | candidate-bound role policy가 complete·partial·orphan group의 구조적 disposition과 role semantic review를 분리하고 deterministic reason으로 fail-closed해야 한다. | Policy [구현], 실제 semantic 승인 [검토 필요] |
| FR-019 | human semantic review가 versioned reviewer authority, exact scope, immutable request·decision lineage와 expiry·revocation·stale evidence 재검증을 거쳐야 한다. | Governance Foundation [구현], 실제 authentication·reviewer 등록 [미구현] |
| FR-020 | candidate-bound bounded sampling으로 JSON schema·MIDI header evidence를 sanitized하게 수집하고 automated analysis와 human semantic approval을 분리해야 한다. | Foundation [구현], 실제 semantic 승인 [검토 필요] |
| FR-021 | trusted provider verification, private principal→opaque reviewer mapping과 기존 ReviewerAuthority를 순서대로 검증하고 인증만으로 reviewer를 자동 등록하지 않아야 한다. | Authentication Foundation [구현], 실제 provider·mapping·authority [미구현] |
| FR-022 | Production authentication provider는 deployment·identity 요구사항에 근거해 명시적으로 선택·활성화하고 missing·disabled·unknown·fake config를 fail-closed해야 한다. | Provider-neutral contract [구현], provider 선택·activation [미구현] |

## 비기능 요구사항

- 긴 작업은 비동기 Job으로 수행합니다.
- Dataset, Artifact, 모델과 Checkpoint를 Git 밖에 둡니다.
- 특정 모델에 종속되지 않는 Adapter 경계를 둡니다.
- 오류를 성공으로 변환하지 않고 구조화된 오류로 반환합니다.
- 로그에는 비밀정보, 원본 Dataset 내용과 절대 경로를 노출하지 않습니다.
- 인증 결과·semantic decision에는 access/refresh/ID token, raw assertion, provider subject와 session secret을 저장하지 않습니다.
