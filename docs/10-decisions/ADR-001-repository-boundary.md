# ADR-001: Repository Boundary

- 상태: 제안됨 [계획]
- 작성일: 2026-08-05
- 최종 수정일: 2026-08-05
- 관련 PR: 이 bootstrap Draft PR에서 확정 예정

## 배경과 문제

DohaMusic은 개인 AI 음악 제작 Workspace이며 Audio 모델의 Dataset, Training과 Runtime까지 소유하면 서비스 책임과 모델 실행 환경이 결합됩니다.

## 결정

DohaAudio가 Music Generation, Instrumental, Stem Separation, Audio Analysis, Dataset, Training, Evaluation, Model Manifest와 Runtime을 소유합니다. DohaMusic은 사용자, Workspace, Project, Lyrics, Recording, Asset, Composition Snapshot, Mix, Export와 Pipeline Orchestration을 소유합니다.

Voice Conversion과 Singing Voice는 계획된 DohaVocal, Lyrics Generation과 Analysis는 DohaLM 책임입니다.

## 선택 이유

- CUDA·PyTorch·모델별 의존성을 서비스 Runtime과 격리합니다.
- Dataset과 모델 lifecycle을 Provider capability에 맞춰 독립적으로 발전시킵니다.
- DohaMusic은 Workspace 일관성과 사용자 기능에 집중할 수 있습니다.

## 대안

1. 모든 AI Runtime을 DohaMusic에 유지: 초기 단순성은 있으나 의존성과 책임이 결합됩니다.
2. 모델마다 저장소 생성: 격리는 강하지만 계약·운영 저장소가 과도하게 늘어납니다.

## 장단점

- 장점: 책임, 배포, 평가와 라이선스 근거가 명확해집니다.
- 단점: Provider 계약, 버전 호환성과 다중 저장소 운영 비용이 생깁니다.

## 영향과 Migration

신규 Audio 기능은 DohaAudio에서 구현합니다. 기존 코드와 Dataset은 별도 승인된 Migration 작업 전까지 이동하지 않습니다. DohaMusic에는 Provider Client와 호환 Adapter를 단계적으로 둡니다.

## 재검토 조건

Provider 경계가 배포·운영 비용을 감당하지 못하거나 독립 Runtime이 기술적으로 불가능하다는 검증 결과가 있을 때 재검토합니다.
