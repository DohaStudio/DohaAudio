# ADR-002: Provider 계약

- 상태: 승인됨 [구현]
- 작성일: 2026-08-05
- 최종 수정일: 2026-08-19
- 관련 PR: 이 bootstrap Draft PR에서 확정 예정

## 배경과 문제

Audio 작업은 장시간 실행되고 GPU와 대용량 Artifact를 사용합니다. Provider 간 직접 호출을 허용하면 작업 상태, 권한, 취소와 자원 조정이 분산됩니다.

## 결정

DohaMusic 제품 서비스와 Workspace·Job Orchestrator만 DohaAudio를 호출합니다. DohaAudio는 DohaVocal과 DohaLM을 직접 호출하지 않습니다. 계약에는 Job 생성, 상태, 취소, 재시도, 오류, Health, capability와 API contract version을 포함합니다.

결과는 로컬 절대 경로 대신 Artifact ID 또는 승인된 URI, checksum과 Metadata로 반환합니다. GPU admission control과 Provider 실행 순서는 DohaMusic이 관리합니다.

## 선택 이유

단일 Workspace·Job Orchestrator가 사용자 권한, Job 상태와 GPU 경쟁을 일관되게 관리할 수 있습니다.

## 대안

1. Provider 간 직접 호출: 국소 구현은 단순하지만 순환 의존과 상태 불일치를 만듭니다.
2. 공유 파일 경로만 전달: 로컬 개발은 쉽지만 배포 경계와 보안을 깨뜨립니다.

## 장단점

- 장점: 추적, 취소, 재시도, 권한과 버전 협상이 중앙화됩니다.
- 단점: Orchestrator 가용성과 계약 설계 품질에 의존합니다.

## 영향과 Migration

학습 전 Runtime Foundation과 HTTP API는 [ADR-005](ADR-005-pre-training-runtime-foundation.md)에 따라 Fake Provider 범위에서 구현했습니다. 실제 모델 Runtime과 DohaMusic Provider Client 통합은 아직 없으며 capability별 단계 검증을 유지합니다.

## 재검토 조건

독립 배포 방식, 다중 GPU scheduler 또는 외부 Provider 연동이 확정되어 현재 계약으로 표현할 수 없을 때 재검토합니다.
