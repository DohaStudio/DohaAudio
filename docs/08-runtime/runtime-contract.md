# Runtime 계약

> 문서 상태: [계획]
> Runtime·HTTP API: [미구현]

DohaAudio Runtime은 모델을 로드하고 capability 작업을 실행하는 독립 Provider Runtime입니다. DohaMusic만 외부 Orchestrator로서 Runtime을 호출합니다.

## 계획된 계약

- Job 생성과 idempotency key
- 상태 조회와 progress
- 취소 요청과 최종 취소 상태
- 명시적 재시도와 attempt 식별자
- 구조화된 오류 code, 재시도 가능 여부와 안전한 message
- Health·readiness·capability 조회
- Provider API contract version
- Artifact ID·URI, checksum, MIME type와 provenance 반환

로컬 절대 경로를 외부 계약으로 반환하지 않습니다. Runtime 내부 경로는 환경 변수로 주입하고 외부에는 Artifact ID 또는 승인된 URI만 노출합니다.

GPU admission control과 여러 Provider의 실행 순서는 DohaMusic이 관리합니다. DohaAudio는 할당받은 작업 범위 안에서 모델 load/unload, 실행 자원과 오류를 관리합니다.

전송 방식은 장기적으로 HTTP 또는 독립 Runtime 계약을 목표로 하지만 endpoint, port와 schema는 아직 확정하지 않았습니다.

## 관련 결정

- [ADR-002 Provider Contract](../10-decisions/ADR-002-provider-contract.md)
- [ADR-004 Artifact Lifecycle](../10-decisions/ADR-004-artifact-lifecycle.md)
