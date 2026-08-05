# ADR-003: Dataset Policy

- 상태: 제안됨 [계획]
- 작성일: 2026-08-05
- 최종 수정일: 2026-08-05
- 관련 PR: 이 bootstrap Draft PR에서 확정 예정

## 배경과 문제

음악 Dataset은 크고 권리·라이선스 제약이 있으며 원본과 파생본을 Git 코드와 함께 두면 유출과 이력 비대화 위험이 큽니다.

## 결정

실제 Dataset은 Git 밖의 `DohaData/audio`에서 관리합니다. `raw`, `interim`, `processed`, `manifests`, `splits`, `licenses` lifecycle을 사용하고 코드에는 절대 경로를 하드코딩하지 않습니다.

Git에는 schema, 전처리·학습 설정 예제, 비식별 소형 fixture와 라이선스 검토 문서만 허용합니다. Dataset 사용 전 출처, 학습 허용, 재배포와 상업 이용 Gate를 독립적으로 확인합니다.

## 선택 이유

코드 이력과 대용량·민감 데이터 lifecycle을 분리하고 Dataset 권리 상태를 명시적으로 차단할 수 있습니다.

## 대안

1. Git LFS에 Dataset 저장: 용량·접근·삭제·라이선스 통제가 충분하지 않습니다.
2. 저장소별 임의 로컬 경로: 재현성과 환경 이식성이 낮습니다.

## 장단점

- 장점: Git 경량화, 권리 Gate, Dataset version과 split 재현성이 향상됩니다.
- 단점: 별도 백업, 접근 제어, Manifest 동기화가 필요합니다.

## 영향과 Migration

기존 `DohaMusic-Datasets`는 즉시 이동하지 않습니다. 파일 수·크기·checksum, 개인정보, 라이선스와 rollback을 포함한 Migration Manifest 승인 후 copy-first 방식으로 전환합니다.

## 재검토 조건

공인 Dataset Registry나 Object Storage가 도입되어 root·URI·접근 정책을 변경해야 할 때 재검토합니다.
