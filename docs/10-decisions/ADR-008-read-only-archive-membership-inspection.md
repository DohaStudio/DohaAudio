# ADR-008: Read-only Archive Membership Inspection

## 상태

Accepted — 2026-08-20

## 배경

Music loop과 Traditional music authority는 ZIP package aggregate만 확인되어 member-level Dataset identity, media, checksum과 provenance를 기존 Enrollment Gate에 제공할 수 없었습니다. archive extraction은 source mutation·Zip Slip·resource amplification 위험을 만들며 권리 evidence가 없는 현재 후보에는 불필요합니다.

## 결정

1. Dataset enrollment와 분리된 `ArchiveInspector` protocol 및 ZIP 전용 `ZipArchiveInspector`를 둡니다.
2. Discovery는 central directory와 metadata만 read-only로 검사하고 filesystem extraction을 금지합니다.
3. member path는 Unicode·separator·encoded traversal을 정규화하며 absolute/drive/UNC/leading slash/`..`와 Windows casefold collision을 차단합니다.
4. member count, filename, uncompressed size와 compression ratio ceiling은 caller-owned immutable policy로 요구합니다. production 권장값을 추측하지 않습니다.
5. encrypted member는 password를 시도하지 않고, nested archive는 재귀 처리하지 않으며, corrupt·partial result를 silent exclusion하지 않습니다.
6. 공개 result에는 archive/member raw filename과 physical path 대신 candidate-bound opaque logical identity를 기록합니다.
7. Discovery CRC metadata와 content SHA-256을 구분합니다. Full checksum은 bounded stream이며 파일을 쓰지 않습니다.
8. complete result만 기존 `DatasetInventory`로 mapping하고 기존 `DatasetEnrollmentService`·`DatasetManifestRegistry`·Rights Gate를 재사용합니다.

## 결과

실제 372 archive의 central directory는 모두 읽혔고 353,883 member가 확인됐습니다. 모든 member 이름이 leading `/`여서 path safety는 false이며 JSON·MIDI는 현행 audio supported media 밖입니다. 실제 member/archive SHA-256, Manifest, DatasetVersion과 split은 발급하지 않았습니다.

Archive inspection 성공은 Dataset rights, integrity 또는 Training readiness를 승인하지 않습니다. path normalization 또는 explicit exclusion/ingestion 정책이 필요하면 별도 검토하며 source archive를 rewrite하지 않습니다.

후속 candidate-specific 해석은 [ADR-009](ADR-009-archive-path-companion-policy.md)에서 결정하며 이 ADR의 generic leading-slash 차단을 변경하지 않습니다.
