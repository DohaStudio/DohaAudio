# Training 전략

> 문서 상태: [계획]
> Training·Fine-tuning: [미구현]

Training은 DohaAudio 책임이며 DohaMusic Runtime과 분리된 환경에서 수행합니다. 대규모 기반 모델의 직접 사전학습은 현재 확정 범위가 아닙니다.

## 계획된 단계

```text
승인된 Dataset Manifest
→ 고정 Split
→ 전처리 계약 검증
→ Training / Fine-tuning Run
→ Checkpoint
→ Evaluation
→ 승인된 Model Manifest
```

각 Run은 Dataset Manifest ID, 설정 checksum, 코드 revision, Runtime environment, seed, 시작·종료 상태와 출력 Artifact ID를 기록해야 합니다. 실패·취소 Run을 성공으로 표시하지 않습니다.

Checkpoint와 log는 `DohaArtifacts/audio`에 저장하며 Git에 포함하지 않습니다. 구체적인 Framework, 모델과 GPU 요구량은 Research 및 실제 검증 후 결정합니다.
