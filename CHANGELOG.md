# 변경 이력

## [미출시]

### 추가

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

- Music Generator, Stem Separation, Music Analysis
- Dataset Migration, Training, Evaluation
- 실제 모델 Adapter·Checkpoint·GPU worker와 영속 DB
- DohaMusic Provider Client와 실제 network 통합
