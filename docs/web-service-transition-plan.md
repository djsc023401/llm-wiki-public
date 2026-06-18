# 웹서비스 전환 계획

이 문서는 외부 Markdown/Git 중심 흐름에서 웹 워크벤치 중심 흐름으로 전환하는 방향을 정리한다.

## 배경

초기 구조는 외부 Markdown 도구와 Git sync를 중심으로 설계되었다. 실제 사용 과정에서는 모바일 입력, Git 동기화, 자동 merge, 원문 이동이 복잡해졌다. 현재 방향은 웹 워크벤치를 기본 입력 표면으로 삼고, Git은 mirror와 감사 이력으로 사용하는 것이다.

## 단계

1. DB note foundation 구축
2. Note API와 웹 워크벤치 제공
3. DB note AI 처리 구현
4. Markdown mirror export 구현
5. 첨부파일, 제안, 일정/알림 확장
6. 대화형 검색과 선택적 AI 답변 계층 추가
7. 외부 Markdown 입력 경로를 기본 흐름에서 제거

## 전환 원칙

- 기존 데이터는 삭제하지 않는다.
- 원문은 보존하고 source note와 연결한다.
- 사람이 승인한 제안만 확정한다.
- Markdown mirror는 DB를 기준으로 만든다.
- public 문서에는 실제 운영 로그를 남기지 않는다.

## 완료 기준

- 사용자가 웹에서 메모 작성부터 AI 처리, 제안 승인, 일정/알림 등록까지 수행할 수 있다.
- 대화형 검색이 source, topic, entity, 원문, 일정, 알림을 함께 활용한다.
- 백업과 restore smoke가 동작한다.
- 외부 Markdown 도구 없이도 일상 사용이 가능하다.
