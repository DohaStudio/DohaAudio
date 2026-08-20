# Archive Path와 Companion Policy

> 문서 상태: candidate-bound path interpretation·companion analysis [구현]
> 실제 Dataset enrollment·Training semantics: [차단·검토 필요]

## 경계

Generic `ZipArchiveInspector`는 leading `/`를 계속 unsafe로 차단합니다. 별도 `ArchivePathInterpretationPolicy`만 candidate ID, policy ID와 version에 결합된 exactly-one-leading-slash convention을 논리 root marker 후보로 해석합니다. source ZIP rename·rewrite·repack·extract는 수행하지 않습니다.

해석 결과는 raw member fingerprint, interpreted member ID와 policy identity를 함께 보존하므로 내부에서 대응을 다시 검증할 수 있습니다. 공개 contract에는 raw filename, physical path와 member content를 포함하지 않습니다. mixed/no-leading/double-leading convention, empty path, traversal, encoded traversal, drive·UNC·colon path와 NFKC·separator·case collision은 fail-closed입니다.

## 실제 path evidence

| candidate | policy | raw members | exactly one `/` | eligible | failures | post-unsafe | collision | interpreted | result |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Music loop | `archive-path/aihub-098/single-root/v1` `1.0.0` | 324,000 | 324,000 | 324,000 | 0 | 0 | 0 | 324,000 | PASS |
| Traditional music | `archive-path/aihub-209/single-root/v1` `1.0.0` | 29,883 | 29,883 | 29,883 | 0 | 0 | 0 | 29,883 | PASS |

Music loop의 evidence fingerprint는 `04255f888f97f3e6813951a304b01dd734da56fb48c4966203a554d694e71f8b`, Traditional music은 `b5f15f00a650f07d88bb586e6ffbea3f1c6d3a083e58e882a7a0277444ffd7c1`입니다. 두 fingerprint는 candidate·logical archive·raw member fingerprint·size·central-directory CRC metadata의 결정적 집계이며 content SHA-256이 아닙니다.

따라서 두 candidate 모두 `RAW_PATH_SAFETY_PASS=false`, `PATH_INTERPRETATION_PASS=true`, `INTERPRETED_PATH_SAFETY_PASS=true`입니다. 이는 다른 archive나 다른 leading-slash pattern을 허용하지 않습니다.

## Companion grouping

Extension을 제거한 interpreted directory-bound path를 casefold한 뒤 opaque group ID로 변환합니다. 같은 basename이라도 directory가 다르면 다른 group입니다. role은 content 의미를 추측하지 않고 `.wav=audio_member`, `.mid/.midi=midi_member`, `.json=json_member`로만 분류합니다.

| candidate | groups | complete JSON+MIDI+WAV | partial | orphan | duplicate role | missing JSON | missing MIDI | missing WAV | result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Music loop | 108,000 | 108,000 | 0 | 0 | 0 | 0 | 0 | 0 | PASS |
| Traditional music | 9,977 | 9,945 | 32 | 16 | 0 | 16 | 16 | 16 | BLOCKED |

Traditional partial 분포는 MIDI+WAV만 있는 group 16개와 JSON만 있는 orphan group 16개입니다. 원본 이름 목록은 기록하지 않습니다.

## Representative probe

각 candidate에서 서로 다른 archive의 JSON 3개를 128 KiB 이하로 bounded full-read하고 MIDI 3개의 14-byte SMF header만 읽었습니다.

- Music loop JSON 3개는 object이며 top-level key가 `dataSet`으로 같았습니다. 공통 key path에서 BPM·music style·source reference 형태가 관찰됐습니다.
- Traditional JSON 3개는 object이며 dataset, music source/type, annotation 정보 계열 top-level key가 같았습니다. tempo·beat·mode·instrument와 source reference 형태 key가 관찰됐습니다.
- Music loop MIDI 3개는 SMF format 1, 2 tracks, division 120이었습니다.
- Traditional MIDI 3개는 SMF format 0/0/1, 1/1/3 tracks, division 480이었습니다.

이는 representative schema/header 관찰일 뿐 전체 content 의미나 supervision 승인이 아닙니다. note sequence, WAV, 전체 JSON/MIDI collection은 읽지 않았습니다.

## Ingestion policy

`CompanionIngestionPolicy`는 `include_primary`, `include_companion`, `metadata_only`, `exclude`, `blocked`, `review_required` 상태를 표현합니다. 현재 두 candidate의 audio/MIDI/JSON/other role은 모두 `review_required`입니다. WAV primary, MIDI symbolic supervision, JSON metadata·label이라는 Training 의미는 아직 확정하지 않습니다.

Music loop는 path와 relationship이 통과해도 policy review와 checksum이 미완료입니다. Traditional music은 relationship도 차단됩니다. 두 candidate 모두 `dataset_inventory_ready=false`, `RIGHTS_GATE_PASS=false`, `DATASET_INTEGRITY_PASS=false`, `DATASET_SPLIT_FROZEN=false`이며 Manifest·DatasetVersion·Split은 발급하지 않았습니다.

Path interpretation ≠ source rewrite, companion relationship ≠ Training semantics, metadata relation ≠ supervision approval, path safety PASS ≠ Dataset integrity PASS입니다.
