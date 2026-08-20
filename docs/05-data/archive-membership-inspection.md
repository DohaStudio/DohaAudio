# Archive Membership Inspection

> 문서 상태: ZIP inspection Foundation [구현]
> 실제 Dataset enrollment: [차단]

## 목적과 경계

`ArchiveInspector`는 archive parser를 Dataset enrollment에서 분리합니다. 현재 구현은 `ZipArchiveInspector`이며 ZIP central directory와 member metadata를 read-only로 조사합니다. `extract()`·`extractall()`·member filesystem write·audio decode를 사용하지 않습니다.

결과는 candidate와 logical archive/member identity, size, CRC metadata, extension/media classification, encryption·nested archive·path safety와 blocking reason을 담습니다. 실제 archive/member filename과 local root는 공개 결과에 포함하지 않습니다.

## 모드와 checksum

- `DISCOVERY`: central directory만 읽으며 archive/member SHA-256과 content CRC 검증을 수행하지 않습니다.
- `FULL_CHECKSUM`: archive file과 지원 member stream을 caller-supplied bounded chunk로 읽어 SHA-256을 계산합니다. member stream을 끝까지 읽어 ZIP CRC도 검증하지만 filesystem output은 만들지 않습니다.

Central-directory CRC는 Dataset content SHA-256이 아닙니다. Discovery inventory는 `missing_checksum_count`를 유지하므로 실제 enrollment integrity를 통과할 수 없습니다. 현재 archive 후보는 Rights Gate도 false이므로 약 97 GB 전체 checksum은 수행하지 않았습니다.

## Path와 resource policy

member 이름은 Unicode NFKC와 slash policy로 검사합니다. `..`, encoded traversal, leading slash, Windows drive, UNC, colon path, empty/null-like name을 차단합니다. separator-normalized·case-insensitive collision도 Dataset identity로 사용할 수 없습니다. raw 이름은 opaque candidate-bound ID로 치환합니다.

member count, filename bytes, per-member/total uncompressed bytes와 compression ratio ceiling은 `ArchiveInspectionPolicy` caller가 명시합니다. 저장소는 근거 없는 production Dataset limit를 기본 권장값으로 고정하지 않습니다. encrypted member는 password를 시도하지 않고 차단하며 nested archive는 재귀 검사하지 않습니다. corrupt/partial archive는 silent skip하지 않습니다.

## 실제 candidate Discovery

2026-08-20 local validation은 production 권장값이 아닌 명시적 inspection ceiling을 사용해 archive를 한 번에 하나씩 검사했습니다. archive/member content SHA-256과 CRC content validation은 수행하지 않았습니다.

| candidate | archive coverage | archive bytes | members | extension | encrypted | nested | corrupt | unsafe path |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| Music loop | 352/352 | 76,561,535,516 | 324,000 | JSON 108,000; MIDI 108,000; WAV 108,000 | 0 | 0 | 0 | 324,000 |
| Traditional music | 20/20 | 20,616,438,224 | 29,883 | JSON 9,961; MIDI 9,961; WAV 9,961 | 0 | 0 | 0 | 29,883 |

두 candidate의 central directory는 모두 읽혔고 member collection은 보이지만 모든 member 이름이 leading `/`로 저장되어 현행 path policy를 통과하지 못합니다. JSON·MIDI는 현행 audio Dataset supported media contract 밖입니다. 따라서 `ARCHIVE_INSPECTION_COMPLETE=true`, `ARCHIVE_MEMBERSHIP_KNOWN=true`, `ARCHIVE_PATH_SAFETY_PASS=false`, inspection status는 `blocked`입니다.

## Enrollment 연결

완전한 `ArchiveInspectionResult`만 기존 `DatasetInventory`로 변환할 수 있습니다. Discovery 결과는 SHA-256이 없어서 integrity가 false이고, blocked/partial result는 변환 자체를 거부합니다. 별도 archive registry나 rights registry는 만들지 않습니다.

Archive visibility ≠ Dataset enrollment이며 Archive membership known ≠ AI Training permission입니다. Music loop과 Traditional music은 AI Training evidence가 없으므로 path policy가 해결되더라도 기존 `DatasetEnrollmentService`에서 계속 차단됩니다.

Candidate-specific leading-slash 해석과 companion grouping은 [Archive Path와 Companion Policy](archive-path-companion-policy.md)에 기록합니다. 이 후속 layer는 raw inspection result와 generic leading-slash 차단을 변경하지 않습니다.
