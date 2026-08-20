# ADR-009: Candidate-specific Archive Path와 Companion Policy

## 상태

Accepted — 2026-08-20

## 배경

PR #8의 generic inspector는 두 실제 candidate의 모든 leading `/` member를 올바르게 fail-closed 처리했습니다. 이 문자가 위험한 filesystem absolute path인지 archive-internal root marker convention인지는 generic parser가 추측할 수 없습니다. JSON·MIDI·WAV 개수도 같지만 개수만으로 companion 관계와 Training 의미를 정할 수 없습니다.

## 결정

1. Generic `ZipArchiveInspector`의 leading-slash 차단은 변경하지 않습니다.
2. 별도 `ArchivePathInterpretationPolicy`를 policy ID·version·candidate ID에 결합하고 exactly-one-leading-slash rule만 명시적으로 해석합니다.
3. raw unsafe 상태, raw member fingerprint, interpreted opaque identity와 evidence fingerprint를 함께 보존합니다. source archive는 rewrite·rename·repack·extract하지 않습니다.
4. mixed/no-leading/double-leading convention과 해석 후 traversal·absolute/drive/UNC/colon·empty path·NFKC/separator/case collision은 fail-closed 합니다.
5. Companion grouping은 interpreted directory-bound stem의 opaque ID와 extension role만 사용합니다. raw filename과 content 의미를 public result에 포함하지 않습니다.
6. `CompanionIngestionPolicy`는 include·metadata-only·exclude·blocked·review 상태를 표현하지만 관계 발견만으로 WAV primary, MIDI supervision 또는 JSON label을 승인하지 않습니다.
7. Representative JSON probe는 bounded schema/key 관찰, MIDI probe는 header 관찰로 제한합니다. 전체 JSON/MIDI parse, audio decode와 checksum scan은 수행하지 않습니다.
8. Path·companion policy는 기존 Rights·Integrity·Enrollment·Training Gate를 우회하지 않습니다.

## 결과

두 candidate의 exactly-one-leading-slash path interpretation은 unsafe·collision 0으로 통과했습니다. Music loop는 108,000개 group이 모두 JSON+MIDI+WAV complete입니다. Traditional music은 9,977개 중 9,945 complete, 32 partial이므로 companion relationship이 차단됩니다.

두 candidate의 role disposition은 모두 `review_required`입니다. 실제 content SHA-256, Rights evidence, Dataset Manifest, DatasetVersion과 split은 없으며 Training Gate도 계속 false입니다.
