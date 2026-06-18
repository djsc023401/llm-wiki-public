# 개발 로드맵

이 문서는 공개용 개발 로드맵이다. 실제 커밋, 요청 ID, 서버 검증 로그는 private notes에 기록한다.

## 완료된 기반

- Docker Compose 기반 API/worker/app DB 구성
- Git mirror 연동
- S3 호환 object storage 연동
- 처리 요청 queue와 worker loop
- Codex CLI runner abstraction
- 웹 워크벤치 `/notes`
- 노트 CRUD, 리비전, 첨부파일, 문서 피드백
- AI 처리와 재분석
- 제안 승인/거절
- 일정/알림과 PWA Push
- 대화형 검색
- 대화 이력 App DB 저장과 서버 기반 후속 질문 맥락
- 백업과 restore smoke

## 현재 중점

- public 전환 가능한 문서와 예시값 정리
- 대화형 검색 품질 개선
- AI 답변 provider 비용/품질 기준 정리
- 운영 로그와 공개 문서 분리
- 범용 기준선을 유지한 개인 운영 흐름 정리

## 다음 목표

1. 다중 사용자 권한 모델 초안 작성
2. 자동 평가용 fixture 확장
3. public demo용 샘플 데이터 작성
4. import/export 경로 일반화
5. 대화 품질 자동 평가와 fixture 확장

## 개인 운영 전환

개인 메모와 일정 관리를 위한 개발은 [개인 운영 전환 계획](./personalization-roadmap.md)을 기준으로 진행한다.

- `generic/base-2026-06-13` 브랜치와 `generic-base-2026-06-13` 태그는 범용 기준선으로 유지한다.
- `master`는 실제 개인 운영 흐름을 빠르게 개선하는 live 브랜치로 사용한다.
- 특정 사용자에게만 맞는 규칙은 코드에 하드코딩하지 않고 DB 설정, 운영 `.env`, 실제 노트 데이터, private notes로 관리한다.
- 공개 문서에는 기능과 예시값만 남기고, 개인 운영 값과 검증 로그는 private notes에 둔다.
