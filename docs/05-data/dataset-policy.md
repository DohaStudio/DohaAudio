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

모든 Dataset은 학습 허용, 목적별 권리, 라이선스 및 상업 이용 Gate를 별도로 통과해야 합니다. local 후보 root는 `DOHAAUDIO_DATASET_ROOT`로 주입하고 실제 위치는 코드·Manifest·API·tracked report에 기록하지 않습니다. 후보는 이동하지 않고 read-only로 조사하며 실제 Migration은 별도 계획과 승인 후 수행합니다.

## 구현 계약

`DatasetManifest`, `DatasetEntry`, `DatasetSplit`과 `DatasetManifestRegistry`는 공통 명세의 identity, version, source, license, `training_allowed`, commercial/redistribution, checksum과 deletion 상태를 고정합니다. `schemas/dataset-manifest.schema.json`과 metadata-only fixture를 제공하며 실제 음원을 포함하지 않습니다.

- `train`, `validation`, `test` membership은 정확히 한 split에 속하고 전체 sample을 포함합니다.
- split은 `algorithm_version`과 `seed`를 기록합니다.
- sample ID·checksum 중복, 누락 membership, overlap, unsupported media type과 manifest checksum 불일치를 차단합니다.
- membership, split, normalization, provenance 또는 권리 상태 변경은 새 DatasetVersion을 요구합니다.
- rights evidence는 안전한 source alias, evidence ID, review status, effective/expiry만 기록하며 원문과 개인 경로는 포함하지 않습니다.
- Admission용 rights snapshot은 candidate·Dataset Manifest identity와 scope를 evidence ID에 결합하며 다른 Dataset의 evidence를 재사용하지 않습니다.
- `training_allowed`는 `true`, `false`, `pending_review`를 사용하며 `true` 외에는 fail-closed 합니다.
- `DatasetAuthorityResolver`는 missing/not-directory root, path traversal, symlink·junction·reparse escape를 차단하고 opaque sample/source ID만 inventory에 남깁니다.
- checksum read는 명시적으로 요청할 때만 수행하고 inventory 과정에서 rename·move·delete·convert·normalize를 수행하지 않습니다.
- 권리 Gate를 통과하지 못한 후보에는 실제 Dataset Manifest·Version·Split을 발급하지 않습니다.
- `RightsEvidenceSource` adapter는 공급자별 raw 문서를 core와 분리하고 path-free `NormalizedRightsEvidence`로 변환합니다.
- `DatasetEnrollmentService`는 보유·접근·AI Training 승인, evidence identity·유효기간, exact inventory와 caller가 명시한 split count가 모두 유효할 때만 기존 `DatasetManifestRegistry`에 등록합니다.
- commercial use, redistribution, derived-model distribution과 generated-output use는 AI Training 승인과 독립적으로 유지합니다.
- `ArchiveInspector`는 concrete ZIP parser를 enrollment에서 분리하고 caller가 명시한 resource policy 아래 central directory와 member metadata를 read-only로 검사합니다.
- archive member 이름은 Unicode·separator·encoded traversal을 정규화하고 leading slash, drive/UNC path, `..`, case-insensitive·separator collision을 차단합니다. 공개 결과에는 raw filename 대신 opaque logical identity만 기록합니다.
- Discovery의 CRC metadata는 content 검증이 아니며 `FULL_CHECKSUM` mode의 bounded stream SHA-256·CRC 검증 전에는 Dataset checksum을 채우지 않습니다.
- encrypted·nested·corrupt·부분 검사와 unsupported member는 숨겨서 제외하지 않으며, 명시적 exclusion 정책이 없으면 candidate enrollment를 차단합니다.
- candidate path interpretation은 generic inspector와 분리하고 policy ID·version·candidate ID·evidence fingerprint를 결합합니다. raw unsafe 상태를 보존하며 exactly-one-leading-slash 외의 pattern과 해석 후 traversal·drive·UNC·colon·collision을 차단합니다.
- companion grouping은 해석된 directory-bound stem의 opaque ID와 extension role만 사용합니다. 관계 완전성은 Training 의미나 ingestion 승인을 뜻하지 않으며 role disposition이 `review_required`이면 inventory를 발급하지 않습니다.

## 관련 결정

- [ADR-003 Dataset Policy](../10-decisions/ADR-003-dataset-policy.md)
- [실제 Dataset Admission 상태](real-dataset-admission.md)
- [ADR-007 Dataset Authority와 Training Admission](../10-decisions/ADR-007-dataset-authority-training-admission.md)
- [ADR-008 Read-only Archive Membership Inspection](../10-decisions/ADR-008-read-only-archive-membership-inspection.md)
- [ADR-009 Candidate-specific Archive Path와 Companion Policy](../10-decisions/ADR-009-archive-path-companion-policy.md)
