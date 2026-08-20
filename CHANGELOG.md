# 변경 이력

## [미출시]

### 추가

- 미확정 deployment·identity 요구를 기록하는 production authentication provider no-selection decision
- secret-free provider config, explicit enablement, fake-production 차단과 no-fallback bootstrap/factory
- 검증 proof를 발급하지 않는 unavailable production adapter와 private mapping store protocol

- 환경 변수로 주입되는 read-only Dataset authority resolver와 path-free logical inventory
- root escape·symlink/junction·unsupported format·checksum·duplicate 차단 계약
- Dataset·rights·split·model·config·environment·execution Gate를 분리한 Training Admission report
- 실제 후보 세 scope의 sanitized inventory와 fail-closed admission 근거
- 공급자 원문과 분리된 normalized rights evidence adapter와 scope별 권리 결정
- exact inventory·evidence 조건을 모두 통과할 때만 Manifest·DatasetVersion·Split을 등록하는 enrollment Gate
- 실제 후보 세 scope의 권리 재검토 결과와 Manifest·Version·Split 미발급 상태
- extract 없이 ZIP central directory와 member metadata를 검사하는 Archive Inspector boundary
- path traversal·Windows path·normalized identity 충돌·encryption·nested archive·corruption·resource limit 차단 계약
- Discovery와 bounded full-checksum mode, path-free `ArchiveInspectionResult`와 기존 enrollment inventory mapping
- archive 후보 372개·353,883 member의 metadata-only 검사 결과와 leading `/` path safety 차단 상태
- generic path 차단을 유지하는 candidate-bound single-leading-slash interpretation policy와 reversible opaque identity
- JSON·MIDI·WAV directory-bound companion grouping 및 include·metadata·exclude·blocked·review disposition 계약
- Music loop 108,000개 complete group과 Traditional music 9,945 complete·32 partial group의 metadata-only 검증 결과
- candidate·path evidence·companion policy에 결합된 structural group·semantic role disposition 계약
- Music complete group의 structural candidate와 Traditional 32개 partial/orphan review-required decision
- candidate·path·companion·role policy에 결합된 deterministic bounded semantic role evidence sampling
- raw value를 보존하지 않는 JSON schema-shape와 14-byte MIDI header consistency summary
- immutable semantic evidence registry와 등록된 human reviewer authority만 승인 가능한 review decision
- Music·Traditional 각각 JSON 32개·MIDI 32개 bounded 검증과 semantic role review-required 유지
- versioned reviewer authority registry와 exact candidate·role·policy·approve/reject scope
- effective·expiry·revocation을 decision 생성과 downstream 소비에서 재검증하는 fail-closed 경계
- immutable semantic review request·resolution·supersession과 one-request/one-decision audit lineage
- authentication과 domain authorization을 분리한 synthetic-only human semantic review workflow
- provider-independent `AuthenticationProvider`와 immutable sanitized `AuthenticatedPrincipal`
- deserialized principal을 신뢰하지 않는 provider-issued verification context와 freshness 검증
- private versioned principal→opaque reviewer identity mapping, revocation·rebind·collision 차단 registry
- authentication·mapping·기존 ReviewerAuthority를 순서대로 재검증하는 authenticated review path
- network·secret 없이 실패 경계를 검증하는 test-only `FakeAuthenticationProvider`

- SQLite 기반 영속 Job repository와 process restart 이후 idempotency·retry lineage 보존
- atomic worker claim·lease, cancellation 관찰, structured failure와 stale-running fail-safe recovery
- 내부 storage reference를 API와 분리하는 `ArtifactResolver` boundary
- Dataset Manifest JSON schema, 불변 DatasetVersion, deterministic split와 integrity validator
- 권리 evidence·expiry·license·training eligibility fail-closed Gate
- immutable TrainingRun·TrainingConfig, preflight readiness와 side-effect-free dry-run
- future Evaluation metadata와 Dataset → TrainingRun → Checkpoint → Evaluation → Model Manifest lineage 계약

- FastAPI 기반 DohaAudio Provider API와 Runtime bootstrap
- `MusicGenerationJob`, `StemSeparationJob`, `AudioAnalysisJob` 공통 상태·진행률·취소·새 Job 재시도 계약
- canonical request fingerprint 기반 idempotency replay와 conflict 방지
- 불변 in-memory Job·Artifact·Model Manifest registry와 구조화된 안전 오류
- 실제 모델을 호출하지 않는 deterministic `FakeAudioProvider`와 세 capability E2E fixture
- Runtime·계약·API·Fake E2E·경로 및 비밀정보 비노출 자동 테스트
- DohaAudio Public Repository의 문서 기반 Architecture와 문서 인덱스 초안
- Repository, Provider, Dataset, Artifact 책임을 결정하는 ADR-001~ADR-004
- 전체 Phase를 `[계획]`으로 정의한 Roadmap
- Dataset·Checkpoint·Model·Artifact·Output·Temp의 Git 제외 정책
- DohaMusic을 제품 서비스와 Workspace·Job Orchestrator로 표현하고 `MusicGenerationJob`과 `StemSeparationJob`의 독립 실행 경계를 명확히 함
- Markdown 제목과 설명을 한국어 공식 문서 언어 기준에 맞게 정리
- DohaStudio 공통 Provider 계약과 공통 용어 문서 참조 추가
- 공통 명세 `0.1.0` / `draft-baseline`의 안정 기준을 `.github` 저장소 `main`으로 고정
- `AudioAnalysisJob`과 `EvaluationJob`을 포함한 네 가지 Job의 독립 실행 및 저장된 AssetVersion·Artifact 입력 원칙 명시
- 코드·문서의 Apache License 2.0 적용과 Dataset·외부 모델·가중치·Checkpoint·Adapter·생성 결과 등의 권리 분리 명시

### 미구현

- 실제 OAuth/OIDC provider, private real identity mapping과 real ReviewerAuthority 등록
- 실제 Music·Traditional human semantic approval/rejection
- 권리 승인된 실제 Dataset Manifest·Split과 TrainingConfig
- Music Generator, Stem Separation, Music Analysis
- 실제 Dataset Migration·decode와 Training·Evaluation 실행
- 실제 모델 Adapter·Checkpoint·GPU worker와 production DB
- DohaMusic Provider Client와 실제 network 통합
