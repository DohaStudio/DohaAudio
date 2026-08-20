# 실제 Dataset Authority Admission 상태

> 조사 기준일: 2026-08-20
> authority ID: `dohaaudio-local-audio-authority-v1`
> 실제 root: 환경 변수로만 주입, tracked 문서·Manifest·API에 비노출

## 조사 방식

후보 authority를 read-only로 조사했습니다. 먼저 directory와 file metadata를 inventory하고, 공개 registry·Manifest·권리 문서를 대조했습니다. 전체 audio decode, archive 해제, 전처리, Dataset 이동과 production Artifact 쓰기는 수행하지 않았습니다. 전체 root에서 reparse point는 발견되지 않았으며 resolver는 향후 symlink·junction·traversal을 fail-closed로 차단합니다.

## 후보별 판정

| candidate ID | 목적 | 발견 상태 | Metadata·권리 근거 | Admission |
|---|---|---|---|---|
| `doha-voice-registry-v1` | Voice Dataset 후보 | raw 39개, 약 494 MB; M4A 25, MP4 12, WAV 2 | public inventory 51 record·유효 SHA-256 51·unique payload 39. 전 항목 unreviewed, rights review required, evaluation only, training approval false | `BLOCKED` |
| `aihub-098-music-loop-package` | Music loop 후보 | ZIP package 352개, 약 76.6 GB | enrolled Manifest·license/terms evidence 없음 | `BLOCKED` |
| `aihub-209-traditional-music-package` | 국악 score/audio 후보 | ZIP package 20개, 약 20.6 GB | enrolled Manifest·license/terms evidence 없음 | `BLOCKED` |

세 후보는 서로 다른 Dataset scope이며 합치지 않습니다. ZIP은 현재 Dataset sample 형식이 아니고 자동 해제하지 않았습니다. Doha Voice의 AAC/M4A·MP4도 현재 DohaAudio Manifest가 허용하는 WAV·FLAC·MP3 범위와 일치하지 않으며, 두 WAV를 포함한 모든 record의 training approval이 false입니다.

## 권리 판정

Doha Voice는 voice consent와 user recording 사실이 기록되어 있지만 작곡·가사·반주 권리는 전 항목 `REVIEW_REQUIRED`, commercial use는 전 항목 `RESTRICTED`입니다. 이는 AI training, 파생 모델 배포, 원본 재배포 또는 생성 결과 상업 이용을 승인하지 않습니다. AIHub 두 후보에는 Dataset identity와 scope에 연결된 license evidence ID, effective date, expiry 및 AI training 허용 근거가 없습니다.

따라서 추측으로 `license_status=approved` 또는 `training_allowed=true`를 만들지 않았고 실제 Dataset Manifest·DatasetVersion·Split도 발급하지 않았습니다.

## Admission Gate

| Gate | 현재 결과 | 근거 |
|---|---|---|
| `DATASET_AUTHORITY_VALID` | 후보별 상이 | Voice logical authority는 식별 가능, AIHub package는 enrolled authority 미완료 |
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
- archive extraction: 0
- Dataset decode: 0
- production Artifact write: 0
- model download/load: 0
- optimizer step: 0
- GPU allocation·Training·Inference: 0
- Checkpoint·Evaluation: 0
- `TRAINING_APPROVAL_CONSUMED`: `false`
