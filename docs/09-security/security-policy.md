# 보안 정책

> 문서 상태: Runtime 요청·응답 보호 [구현], 운영 인증·권한 [계획]

## 저장소 보호

- Dataset, 음원, 모델 weight, Checkpoint와 Runtime Artifact를 Git에 포함하지 않습니다.
- `.env`와 token, credential, 실제 내부 경로를 커밋하지 않습니다.
- 공개 Manifest와 log에서 사용자 식별자, 원본 파일명과 절대 경로를 제거합니다.
- 의존성·모델·Dataset 출처와 checksum을 검증합니다.

## 권리와 상업 이용

이 저장소의 코드와 문서는 [Apache License 2.0](../../LICENSE)을 따릅니다. Dataset, 외부 모델, 모델 가중치, Checkpoint, Adapter, 생성 음원, Stem 결과, 평가 샘플과 제3자 콘텐츠에는 저장소의 Apache-2.0이 적용되지 않습니다.

코드, 외부 모델, 모델 가중치와 Dataset 라이선스를 독립적으로 검토합니다. 저장소 라이선스 확인만으로 Dataset 학습, 생성 결과의 상업 이용 또는 모델 재배포가 승인되었다고 판단하지 않습니다. 각 항목의 출처, 권리자, 이용 범위와 상업 이용 조건을 별도로 확인하고 기록해야 합니다.

## Provider 경계

Provider 인증·권한 계약은 DohaMusic과 함께 확정해야 합니다. DohaAudio는 다른 Provider로 요청을 전달하지 않으며, 오류 응답과 log에 비밀정보 또는 Dataset 내용을 포함하지 않습니다.

Runtime은 Windows·Linux·UNC·home 절대 경로와 `file:` URI를 거부합니다. `token`, `secret`, `api_key`, `credential`, `password` 및 `access_token`, `client_secret`, `api-key` 같은 변형 설정 key도 요청에서 거부합니다. API validation과 내부 예외는 stack trace, raw exception과 payload를 반향하지 않는 구조화된 오류로 변환합니다. 자동 테스트는 경로·비밀정보·stack trace 비노출을 검증합니다.

SQLite DB 위치와 ArtifactResolver의 storage reference는 composition root에 주입하는 내부 정보이며 API·Manifest·structured error에 공개하지 않습니다. Dataset fixture는 logical sample ID, synthetic checksum과 안전한 source alias만 포함합니다. 실제 Dataset·권리 evidence 원문·사용자 DB·PID·command·environment에는 접근하지 않습니다.

Dataset authority의 실제 root는 선택된 환경 변수에서만 읽고 외부 모델에는 authority ID, candidate ID와 opaque source key만 남깁니다. resolver는 symlink·junction·reparse point와 traversal을 차단하며 inventory는 파일을 변경하지 않습니다. tracked report에는 원본 파일명, 상대 경로, private registry row와 local root를 포함하지 않습니다.

Rights evidence adapter에는 sanitized source alias, logical identity, review/effective/expiry와 scope decision만 전달합니다. account·request ID, 사용자 이름·email, private URL, token, credential, 원문과 로컬 경로는 tracked fixture·Manifest·report에 복사하지 않습니다.

Archive inspection은 `extract()`·`extractall()`과 filesystem member write를 사용하지 않습니다. member 이름은 traversal·absolute/drive/UNC path·encoded traversal·case-insensitive collision을 검사하고, 외부 결과에는 raw archive/member filename 대신 candidate-bound opaque identity만 둡니다. encrypted·nested·corrupt member와 caller-supplied size·count·ratio ceiling 초과는 fail-closed 합니다.

Role disposition decision은 candidate·path evidence·companion policy exact binding을 요구하고 safe reason code와 opaque group ID만 공개합니다. Partial/orphan을 silent include하지 않으며 policy-level exclusion도 source archive 삭제나 rewrite를 수행하지 않습니다.

Candidate path interpretation은 generic security exception이 아닙니다. candidate·policy identity에 결합된 exactly-one-leading-slash evidence만 별도 logical view로 해석하고 raw unsafe 상태를 보존합니다. interpreted result에는 raw filename 대신 fingerprint·opaque member/group ID만 남기며 mixed/double-leading pattern과 해석 후 traversal·drive·UNC·colon·collision은 차단합니다. Companion probe는 bounded representative JSON key summary와 MIDI header로 제한하고 raw value·binary·filename을 tracked output에 복사하지 않습니다.

Training readiness는 rights/license/eligibility가 불명확하거나 evidence가 누락·미검토·만료된 경우 `BLOCKED`로 fail-closed 합니다. Dataset license, training permission, commercial usage, redistribution, model/weight license를 하나의 boolean으로 합치지 않습니다.
