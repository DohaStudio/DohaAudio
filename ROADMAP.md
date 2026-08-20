# DohaAudio 로드맵

> 문서 상태: [계획]

| Phase | 목표 | 상태 | 주요 산출물 |
|---|---|---|---|
| 1 | Repository Foundation | [계획] | 문서 체계, 작업 규칙, 기본 계약 |
| 2 | Dataset Strategy | [진행 중] | Manifest·Version·split·integrity·rights evidence·authority/enrollment·archive inspection Gate [구현], 승인 Dataset 0개 |
| 3 | Training | [진행 중] | Run/config·preflight·dry-run [구현], optimizer 실행 [미구현] |
| 4 | Music Generation | [계획] | 교체 가능한 Music Generator와 Instrumental 기능 |
| 5 | Stem Separation | [계획] | Stem 모델 Adapter와 출력 계약 |
| 6 | Music Analysis | [계획] | BPM, Key, Structure, Audio Quality 분석 |
| 7 | Runtime | [진행 중] | SQLite Job·Worker Foundation [구현], 실제 모델 Runtime [미구현] |
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

학습 전 Runtime·Readiness·Admission Foundation은 SQLite Job persistence, worker claim/recovery, Dataset authority resolver·inventory, rights validation, ZIP central-directory membership inspection과 read-only dry-run 범위에서 구현했습니다. 실제 후보 세 scope는 모두 fail-closed로 차단됐습니다. 이는 Phase 2·3·7·8 전체 완료 판정이 아니며 archive extraction, Dataset Migration, 모델 다운로드·load, optimizer step, Checkpoint, 실제 Music Generation·Stem Separation·Audio Analysis, GPU Runtime과 DohaMusic 실제 연동은 수행하지 않았습니다.
