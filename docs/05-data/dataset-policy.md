# Dataset 정책

> 문서 상태: Dataset 계약·검증 [구현]
> 실제 Dataset Migration·decode: [미구현]

DohaAudio의 Dataset 기준 루트는 `DohaData/audio`입니다.

```text
DohaData/audio/
├── raw/
├── interim/
├── processed/
├── manifests/
├── splits/
└── licenses/
```

| 영역 | 책임 |
|---|---|
| `raw` | 변경하지 않는 원본과 공급자 package |
| `interim` | 재생성 가능한 중간 처리 결과 |
| `processed` | 검증된 학습·평가 입력 후보 |
| `manifests` | Dataset item, checksum, provenance와 lifecycle |
| `splits` | 누수 방지 기준이 기록된 train/validation/test split |
| `licenses` | 출처, 약관, 저작권과 상업 이용 검토 증거 |

## Git 허용

- Dataset·Manifest schema
- 전처리 및 split 설정 예제
- 라이선스 검토 양식
- 비식별 소형 test fixture

## Git 금지

- 원본·전처리 음원과 대규모 archive
- 실제 학습 Dataset record와 민감 경로
- 개인정보·동의 증적 원본
- 생성 음원, cache, 모델 weight와 Checkpoint

모든 Dataset은 학습 허용, 목적별 권리, 라이선스 및 상업 이용 Gate를 별도로 통과해야 합니다. 기존 `DohaMusic-Datasets`의 실제 이동은 별도 Migration 계획과 승인 후 수행합니다.

## 구현 계약

`DatasetManifest`, `DatasetEntry`, `DatasetSplit`과 `DatasetManifestRegistry`는 공통 명세의 identity, version, source, license, `training_allowed`, commercial/redistribution, checksum과 deletion 상태를 고정합니다. `schemas/dataset-manifest.schema.json`과 metadata-only fixture를 제공하며 실제 음원을 포함하지 않습니다.

- `train`, `validation`, `test` membership은 정확히 한 split에 속하고 전체 sample을 포함합니다.
- split은 `algorithm_version`과 `seed`를 기록합니다.
- sample ID·checksum 중복, 누락 membership, overlap, unsupported media type과 manifest checksum 불일치를 차단합니다.
- membership, split, normalization, provenance 또는 권리 상태 변경은 새 DatasetVersion을 요구합니다.
- rights evidence는 안전한 source alias, evidence ID, review status, effective/expiry만 기록하며 원문과 개인 경로는 포함하지 않습니다.
- `training_allowed`는 `true`, `false`, `pending_review`를 사용하며 `true` 외에는 fail-closed 합니다.

## 관련 결정

- [ADR-003 Dataset Policy](../10-decisions/ADR-003-dataset-policy.md)
