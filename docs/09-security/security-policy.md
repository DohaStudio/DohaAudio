# 보안 정책

> 문서 상태: [계획]

## 저장소 보호

- Dataset, 음원, 모델 weight, Checkpoint와 Runtime Artifact를 Git에 포함하지 않습니다.
- `.env`와 token, credential, 실제 내부 경로를 커밋하지 않습니다.
- 공개 Manifest와 log에서 사용자 식별자, 원본 파일명과 절대 경로를 제거합니다.
- 의존성·모델·Dataset 출처와 checksum을 검증합니다.

## 권리와 상업 이용

코드, 모델 코드, 모델 weight와 Dataset 라이선스를 독립적으로 검토합니다. 라이선스 확인만으로 Dataset 학습, 생성 결과의 상업 이용 또는 모델 재배포가 승인되었다고 판단하지 않습니다.

## Provider 경계

Provider 인증·권한 계약은 DohaMusic과 함께 확정해야 합니다. DohaAudio는 다른 Provider로 요청을 전달하지 않으며, 오류 응답과 log에 비밀정보 또는 Dataset 내용을 포함하지 않습니다.
