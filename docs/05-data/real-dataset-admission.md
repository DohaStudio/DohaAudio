# 실제 Dataset Authority Admission 상태

> 조사 기준일: 2026-08-20
> authority ID: `dohaaudio-local-audio-authority-v1`
> 실제 root: 환경 변수로만 주입, tracked 문서·Manifest·API에 비노출

## 조사 방식

후보 authority를 read-only로 조사했습니다. 먼저 directory와 file metadata를 inventory하고, 공개 registry·Manifest·권리 문서를 대조했습니다. ZIP 후보는 central directory metadata를 읽고 candidate당 JSON 3개와 MIDI header 3개만 bounded probe했습니다. 전체 member payload bulk read, audio decode, archive 해제, 전처리, Dataset 이동과 production Artifact 쓰기는 수행하지 않았습니다. 전체 root에서 reparse point는 발견되지 않았으며 resolver는 향후 symlink·junction·traversal을 fail-closed로 차단합니다.

## 후보별 inventory 재검증

| candidate ID | 목적 | 발견 상태 | Metadata·권리 근거 | Admission |
|---|---|---|---|---|
| `doha-voice-registry-v1` | Voice Dataset 후보 | raw 39개, 494,457,933 bytes; M4A 25, MP4 12, WAV 2 | public inventory 51 record·유효 SHA-256 51·unique payload 39. 전 항목 unreviewed, rights review required, evaluation only, training approval false | `BLOCKED` |
| `aihub-098-music-loop-package` | Music loop 후보 | ZIP package 352개, 76,561,535,516 bytes | archive 외부 enrolled Manifest·license/terms evidence 없음 | `BLOCKED` |
| `aihub-209-traditional-music-package` | 국악 score/audio 후보 | ZIP package 20개, 20,616,438,224 bytes | archive 외부 enrolled Manifest·license/terms evidence 없음 | `BLOCKED` |

세 후보는 서로 다른 Dataset scope이며 합치지 않습니다. ZIP은 현재 Dataset sample 형식이 아니고 자동 해제하지 않았습니다. Doha Voice의 AAC/M4A·MP4도 현재 DohaAudio Manifest가 허용하는 WAV·FLAC·MP3 범위와 일치하지 않으며, 두 WAV를 포함한 모든 record의 training approval이 false입니다.

## 권리 판정

Doha Voice는 voice consent와 user recording 사실이 기록되어 있지만 작곡·가사·반주 권리는 전 항목 `REVIEW_REQUIRED`, commercial use는 전 항목 `RESTRICTED`입니다. 이는 AI training, 파생 모델 배포, 원본 재배포 또는 생성 결과 상업 이용을 승인하지 않습니다. AIHub 두 후보에는 Dataset identity와 scope에 연결된 license evidence ID, effective date, expiry 및 AI training 허용 근거가 없습니다.

따라서 추측으로 `license_status=approved` 또는 `training_allowed=true`를 만들지 않았고 실제 Dataset Manifest·DatasetVersion·Split도 발급하지 않았습니다.

## Rights evidence 재검토

| candidate ID | authoritative evidence | AI Training | commercial | redistribution·derived model | review·expiry |
|---|---|---|---|---|---|
| `doha-voice-registry-v1` | 추적된 rights policy·rights review·consent/license registry. source fingerprint ID `voice-rights-policy-a4f2cae9b2e9`, `voice-rights-review-59788ecf4588` | 명시적 승인 0건, `denied` | `restricted` | 승인 근거 없음 | 현재 부정 판정 확인, expiry 없음 |
| `aihub-098-music-loop-package` | archive 외부 evidence 없음 | `unknown` | `unknown` | `unknown` | review 불가 |
| `aihub-209-traditional-music-package` | archive 외부 evidence 없음 | `unknown` | `unknown` | `unknown` | review 불가 |

Voice evidence는 candidate-level 차단 근거이며 승인 Dataset Manifest가 없으므로 enrollment용 Manifest identity에 결합하지 않았습니다. AIHub의 directory 이름과 `Training` 하위 이름은 공급자 Training permission을 의미하지 않습니다. Bounded representative probe를 Rights 또는 Training 의미의 근거로 사용하지 않았습니다.

## Archive membership inspection

| candidate ID | coverage | member count | extension summary | encrypted | nested | corrupt | path safety |
|---|---:|---:|---|---:|---:|---:|---|
| `aihub-098-music-loop-package` | 352/352 | 324,000 | JSON·MIDI·WAV 각 108,000 | 0 | 0 | 0 | 324,000 leading `/`, `false` |
| `aihub-209-traditional-music-package` | 20/20 | 29,883 | JSON·MIDI·WAV 각 9,961 | 0 | 0 | 0 | 29,883 leading `/`, `false` |

두 candidate의 central directory는 모두 읽혔으므로 member collection visibility는 확보됐습니다. 그러나 모든 member 이름이 leading `/`로 저장되어 normalized relative path policy를 통과하지 못합니다. WAV는 media candidate로 분류되지만 unsafe path 때문에 지원 member가 아니며 JSON·MIDI는 현행 audio Dataset media contract 밖입니다. Discovery는 central-directory CRC metadata만 확인하고 content CRC·SHA-256을 검증하지 않았습니다.

## Candidate path interpretation과 companion 관계

Generic raw path 차단은 유지하면서 candidate별 exactly-one-leading-slash evidence를 독립 검증했습니다. 두 candidate 모두 member 전체가 같은 convention이며 제거 후 traversal·absolute/drive/UNC/colon·empty path와 NFKC·separator·case collision은 0이어서 interpreted path safety는 통과했습니다.

| candidate ID | path interpretation | groups | complete | partial | orphan | duplicate role | companion result |
|---|---|---:|---:|---:|---:|---:|---|
| `aihub-098-music-loop-package` | 324,000/324,000 PASS | 108,000 | 108,000 | 0 | 0 | 0 | PASS |
| `aihub-209-traditional-music-package` | 29,883/29,883 PASS | 9,977 | 9,945 | 32 | 16 | 0 | BLOCKED |

JSON·MIDI representative probe는 candidate당 3개로 제한했습니다. JSON은 schema/key summary만, MIDI는 14-byte SMF header만 관찰했습니다. role은 extension-based `audio_member`·`midi_member`·`json_member`이며 실제 ingestion disposition은 모두 `review_required`입니다.

## Dataset enrollment

| candidate ID | Manifest enrolled | DatasetVersion issued | inventory match | split frozen | blocker |
|---|---:|---:|---:|---:|---|
| `doha-voice-registry-v1` | no | no | 미검증 | no | AI Training 승인 false, unsupported 37개, current checksum 미완료 |
| `aihub-098-music-loop-package` | no | no | 미검증 | no | evidence 없음, role policy review, content checksum 미계산 |
| `aihub-209-traditional-music-package` | no | no | 미검증 | no | evidence 없음, 32 partial companion group, role policy review, content checksum 미계산 |

실제 후보에서 missing member, extra member, identity/checksum/media/provenance mismatch를 0으로 증명할 Manifest가 없으므로 integrity를 통과로 표시하지 않습니다. 승인 후보용 synthetic contract test에서만 exact match와 deterministic split·version immutability를 검증합니다.

## Admission Gate

| Gate | 현재 결과 | 근거 |
|---|---|---|
| `DATASET_AUTHORITY_VALID` | 세 후보 `true` | 각각 별도 exact scope와 logical candidate identity를 read-only로 재확인 |
| `ARCHIVE_INSPECTION_COMPLETE` | archive 후보 `true` | 372/372 central directory를 끝까지 검사 |
| `ARCHIVE_MEMBERSHIP_KNOWN` | archive 후보 `true` | central directory의 전체 member collection과 safe opaque identity 확인 |
| `ARCHIVE_PATH_SAFETY_PASS` | archive 후보 `false` | 모든 member 이름이 leading `/` |
| `PATH_INTERPRETATION_PASS` | archive 후보 `true` | candidate별 exactly-one-leading-slash evidence와 해석 후 path guard 통과 |
| `INTERPRETED_PATH_SAFETY_PASS` | archive 후보 `true` | 해석 후 unsafe·collision 0; generic raw 상태와 별도 |
| `COMPANION_RELATIONSHIP_PASS` | Music loop `true`, Traditional `false` | Traditional에 missing-role partial group 32개 |
| `RIGHTS_GATE_PASS` | `false` | 승인 evidence 없음 또는 review/restriction 상태 |
| `DATASET_INTEGRITY_PASS` | `false` | 승인 membership·현재 content checksum 재검증·지원 형식 정책 미완료 |
| `DATASET_SPLIT_FROZEN` | `false` | 승인 Dataset Manifest가 없어 split 미발급 |
| `MODEL_SELECTED` | `false` | DohaAudio Music Generation training model/base architecture 미확정 |
| `TRAINING_CONFIG_VALID` | `false` | authoritative batch·learning rate·limit·precision·cadence 없음 |
| `ENVIRONMENT_PREFLIGHT_PASS` | `false` | 하드웨어 inventory만 확인, model/config compatibility 미검증 |
| `TRAINING_PREFLIGHT_PASS` | `false` | 실제 Manifest·config가 없어 PR #5 preflight 입력 불가 |
| `TRAINING_EXECUTION_READY` | `false` | 선행 Gate와 별도 실행 승인 미충족 |

환경 inventory는 Python 3.12.5, NVIDIA RTX 3060 Ti 8,192 MiB, driver 610.62, CUDA compiler 미발견입니다. CUDA allocation, framework import, model load와 benchmark는 수행하지 않았으므로 이 값은 compatibility 또는 권장 VRAM 근거가 아닙니다.

## Preprocessing 계약 상태

resampling, channel handling, normalization, duration, silence 및 corrupt/unsupported file 정책은 model/framework 선택 후 caller가 명시해야 합니다. 현재는 값을 추측하지 않으며 `PreprocessingContract`가 모든 항목의 명시를 요구합니다. 전체 Dataset resample·conversion·normalization output은 생성하지 않았습니다.

## Side-effect 계수

- 원본 Dataset mutation: 0
- archive mutation: 0
- archive extraction: 0
- extracted file: 0
- Dataset decode: 0
- bounded JSON representative parse: 6
- MIDI header-only probe: 6
- 전체 JSON/MIDI collection parse: 0
- production Artifact write: 0
- model download/load: 0
- optimizer step: 0
- GPU allocation·Training·Inference: 0
- Checkpoint·Evaluation: 0
- `TRAINING_APPROVAL_CONSUMED`: `false`

## 경고

- Dataset possession ≠ Training permission
- Archive visibility ≠ Dataset enrollment
- Archive membership known ≠ AI Training permission
- Path interpretation ≠ source rewrite
- Companion relationship ≠ Training semantics
- Inspection PASS ≠ Integrity PASS
- Integrity PASS ≠ Training Ready
- Training permission ≠ commercial permission
- commercial permission ≠ redistribution permission
- `PRE_TRAINING_READY` ≠ `TRAINING_EXECUTION_READY`
