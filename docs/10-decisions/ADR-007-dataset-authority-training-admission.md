# ADR-007: Dataset Authority와 Training Admission

## 상태

승인됨 [구현]

## 배경

Pre-Training Readiness fixture가 통과해도 local Dataset 보유, Dataset 권리, model 선택, Training 설정과 실행 승인은 서로 다른 사실입니다. local root를 곧바로 승인 Dataset으로 취급하거나 하나의 READY 값으로 합치면 권리와 실행 side effect가 fail-open 될 수 있습니다.

## 결정

1. Dataset root는 `DOHAAUDIO_DATASET_ROOT`로 주입하고 내부 `ResolvedDatasetAuthority`에서만 실제 경로를 보유합니다.
2. 공개 inventory는 logical authority/candidate/sample/source ID, media type, size와 checksum만 사용합니다.
3. traversal, symlink, junction과 reparse point가 authority root를 벗어나면 차단합니다.
4. inventory와 checksum은 read-only이며 원본 rename·move·delete·변환·정규화를 금지합니다.
5. 권리 evidence, training permission, commercial use와 redistribution을 독립적으로 판단합니다.
   evidence는 candidate·Dataset Manifest identity와 허용 scope가 일치할 때만 해당 Gate에 사용합니다.
6. 권리 Gate를 통과하지 못한 후보에는 Dataset Manifest·Version·Split을 발급하지 않습니다.
7. Dataset authority, rights, integrity, split, model, config, environment, preflight와 execution Gate를 분리합니다.
8. execution ready는 모든 Gate와 별도 Training 승인 소비가 참일 때만 가능합니다.

## 결과

현재 발견된 후보는 각각 권리 미검토·제한, unsupported package 또는 Manifest 부재로 차단됩니다. 실제 Dataset Manifest, TrainingConfig, started TrainingRun, Checkpoint와 Evaluation은 생성하지 않습니다. 새로운 근거가 생기면 기존 결과를 수정하지 않고 새 DatasetVersion과 admission 기록을 만듭니다.
