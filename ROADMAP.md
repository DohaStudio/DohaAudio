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
| 7 | Runtime | [계획] | 독립 Runtime, 작업 상태·취소·재시도 |
| 8 | Provider API | [계획] | 버전이 지정된 DohaMusic 연동 API |
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

이번 bootstrap은 향후 Phase를 정의하는 문서 작업일 뿐 Phase 1 완료 판정이 아닙니다. Dataset Migration, 모델 다운로드, Training, Music Generation, Runtime 및 Provider API 구현은 수행하지 않았습니다.
