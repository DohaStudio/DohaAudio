# Contributing to DohaAudio

## 브랜치

- `main`: 안정화된 버전
- `develop`: 일반 작업의 통합 대상
- 작업 브랜치: 최신 `develop`에서 생성

작업 브랜치는 `docs/<name>`, `feat/<name>`, `fix/<name>` 형식을 사용합니다. `main`과 `develop`에 직접 커밋하지 않습니다.

## 변경 원칙

- Provider 경계와 기존 ADR을 먼저 확인합니다.
- Dataset, 음원, Checkpoint, 모델 weight, Artifact와 비밀정보를 Git에 추가하지 않습니다.
- 구현되지 않은 기능은 `[계획]`, `[미구현]`, 불확실한 항목은 `[검증 필요]`로 표시합니다.
- 모델 성능, VRAM, 라이선스 및 상업 이용 가능 여부를 추측하지 않습니다.
- Provider가 다른 Provider를 직접 호출하는 코드를 추가하지 않습니다.

## Pull Request

PR 대상은 `develop`입니다. 본문에는 작업 내용, 변경 파일, 검증 결과, 문서 영향, 미구현·후속 작업을 기록합니다. 구현 변경에는 관련 테스트, 문서와 `CHANGELOG.md`를 포함합니다.
