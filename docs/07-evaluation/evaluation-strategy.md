# 평가 전략

> 문서 상태: [계획]
> Evaluation pipeline: [미구현]

Evaluation은 capability별 정량 지표, 사람 평가, 라이선스·운영 Gate를 분리합니다.

## 영역

- Music Generation 품질과 prompt/condition 일치도
- Instrumental 요구 충족 여부
- Stem Separation의 누출·왜곡·잔향
- BPM·Key·Structure 분석 정확도
- Audio Quality, clipping, loudness와 artifact
- Runtime 지연 시간, 최대 VRAM, 오류·취소·재시도

평가 Dataset은 Training Dataset과 누수를 방지하고 Manifest와 Split ID로 고정합니다. 측정하지 않은 수치와 비교 결과는 작성하지 않습니다. 결과는 `DohaArtifacts/audio/evaluations`에 두고 `evaluation_result_id`로 Model Manifest에 연결합니다.
