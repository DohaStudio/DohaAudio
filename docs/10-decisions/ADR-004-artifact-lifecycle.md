# ADR-004: Artifact 수명 주기

- 상태: 제안됨 [계획]
- 작성일: 2026-08-05
- 최종 수정일: 2026-08-05
- 관련 PR: 이 bootstrap Draft PR에서 확정 예정

## 배경과 문제

Checkpoint, 생성 음원, Stem, 평가와 Run은 재현·감사에 필요하지만 크고 Runtime별 경로에 결합되기 쉽습니다. DohaMusic Workspace 결과와 Provider 결과도 구분해야 합니다.

## 결정

DohaAudio Provider Artifact는 다음 Git 외부 구조를 사용합니다.

```text
DohaArtifacts/audio/
├── checkpoints/
├── models/
├── generations/
├── stems/
├── evaluations/
└── runs/
```

재생성 가능한 cache, temporary output과 venv는 다음에 둡니다.

```text
DohaTemp/audio/
├── cache/
├── temporary-output/
└── venv/
```

Mix, Export, Preview와 Composition Snapshot은 DohaAudio Artifact가 아니라 DohaMusic이 소유하는 `DohaArtifacts/music` Workspace 결과입니다.

Artifact는 ID, kind, version, checksum, format, size, producer, model/version, run ID, 생성 시각과 보존 상태를 갖습니다. 외부 계약에는 로컬 절대 경로를 넣지 않습니다.

## 선택 이유

Provider 출력, Workspace 결과와 임시 파일을 분리해 보존·삭제·재현 정책을 다르게 적용할 수 있습니다.

## 대안

1. 모든 결과를 Project 폴더에 저장: Provider 재현 정보와 Workspace 소유권이 혼재됩니다.
2. Runtime 절대 경로 반환: 단일 PC 밖으로 확장하기 어렵고 경로 정보가 노출됩니다.

## 장단점

- 장점: lifecycle, checksum, provenance와 저장소 경계가 명확합니다.
- 단점: Artifact catalog와 ID/URI resolver 구현이 필요합니다.

## 영향과 Migration

현재 폴더와 파일은 생성하지 않습니다. Runtime 구현 전에 Artifact Metadata schema와 DohaMusic 인수 계약을 먼저 확정하고 capability별로 도입합니다.

## 재검토 조건

Object Storage, 원격 Runtime, Artifact retention 또는 삭제 정책이 확정되어 현재 구조를 확장해야 할 때 재검토합니다.
