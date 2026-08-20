# 변경 이력

## [미출시]

### 추가

- 환경 변수로 주입되는 read-only Dataset authority resolver와 path-free logical inventory
- root escape·symlink/junction·unsupported format·checksum·duplicate 차단 계약
- Dataset·rights·split·model·config·environment·execution Gate를 분리한 Training Admission report
- 실제 후보 세 scope의 sanitized inventory와 fail-closed admission 근거

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

- 권리 승인된 실제 Dataset Manifest·Split과 TrainingConfig
- Music Generator, Stem Separation, Music Analysis
- 실제 Dataset Migration·decode와 Training·Evaluation 실행
- 실제 모델 Adapter·Checkpoint·GPU worker와 production DB
- DohaMusic Provider Client와 실제 network 통합
