# 프로젝트 범위

> 문서 상태: [계획]

DohaAudio는 DohaMusic이 호출하는 Audio AI Provider입니다. Dataset에서 모델을 준비하고 평가한 뒤 독립 Runtime으로 음악·Stem·분석 결과를 제공하는 책임을 갖습니다.

## 포함 범위

- Music·Instrumental Generation
- Stem Separation
- BPM·Key·Structure·Quality Analysis
- Music Dataset Pipeline
- Training·Fine-tuning·Evaluation
- Model Registry·Manifest·Runtime·Provider API

## 제외 범위

- 사용자, 인증, Workspace와 Project
- Lyrics와 Recording 관리
- Composition Snapshot, Mix와 Export
- Singing Voice와 Voice Conversion
- Lyrics Generation과 Analysis

Workspace 책임은 [DohaMusic](https://github.com/DohaStudio/DohaMusic), Vocal 책임은 계획된 `DohaVocal`, 언어 모델 책임은 `DohaLM`에 둡니다.
