# DohaAudio 로드맵

> 문서 상태: [계획]

| Phase | 목표 | 상태 | 주요 산출물 |
|---|---|---|---|
| 1 | Repository Foundation | [계획] | 문서 체계, 작업 규칙, 기본 계약 |
| 2 | Dataset Strategy | [계획] | Dataset schema, Manifest, split, license gate |
| 3 | Training | [계획] | Training/Fine-tuning pipeline, run metadata |
| 4 | Music Generation | [계획] | 교체 가능한 Music Generator와 Instrumental 기능 |
| 5 | Stem Separation | [계획] | Stem 모델 Adapter와 출력 계약 |
| 6 | Music Analysis | [계획] | BPM, Key, Structure, Audio Quality 분석 |
| 7 | Runtime | [진행 중] | Fake Runtime Foundation [구현], 실제 모델 Runtime [미구현] |
| 8 | Provider API | [진행 중] | 계약 API [구현], DohaMusic 실제 연동 [미구현] |
| 9 | Evaluation | [계획] | 모델별 정량·정성 평가와 회귀 기준 |
| 10 | Stable Release | [계획] | 고정 계약, 운영 문서, 릴리스 검증 |

## 공통 완료 조건

- 책임 경계와 ADR 일치
- Dataset·Artifact가 Git 밖에 유지됨
- 모델·Dataset·라이선스·상업 이용 상태 기록
- 관련 테스트와 재현 가능한 검증 결과 존재
- README, 문서, CHANGELOG 최신화
- DohaMusic Provider 계약 호환성 확인

## 현재 범위

학습 전 Runtime Foundation은 in-memory persistence와 Fake Provider 범위에서 구현했습니다. 이는 Phase 7·8 전체 완료 판정이 아닙니다. Dataset Migration, 모델 다운로드, Training, 실제 Music Generation·Stem Separation·Audio Analysis, GPU Runtime과 DohaMusic 실제 연동은 수행하지 않았습니다.
