# 변경 이력

## [미출시]

### 추가

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
- Runtime과 Provider API
