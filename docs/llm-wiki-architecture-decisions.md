# 아키텍처 결정 기록

이 문서는 공개 가능한 아키텍처 결정만 요약한다.

## 1. ORM을 사용하지 않는다

DB 접근은 raw SQL과 명시적 repository 함수로 구현한다. 이유는 schema 변화와 운영 SQL을 직접 통제하기 위해서다.

## 2. 웹 워크벤치를 기본 사용 표면으로 둔다

외부 Markdown 도구와 Git 동기화는 강력하지만 모바일 입력과 충돌 관리가 복잡하다. 웹 워크벤치는 작성, 처리, 검토, 검색을 한 화면에서 제공한다.

## 3. AI 결과는 제안으로 둔다

AI가 만든 태그, 주제, 대상, 일정은 자동 확정하지 않는다. 사람이 승인해야 DB 연결과 일정으로 반영된다.

## 4. Git은 mirror와 감사 이력으로 사용한다

DB가 canonical storage가 되고, Markdown mirror는 감사와 외부 소비를 위한 보조 경로가 된다.

## 5. Runner abstraction을 둔다

Codex CLI, OpenAI API, dry-run runner를 바꿔 사용할 수 있게 한다. 운영 기본값은 환경에 따라 선택한다.

## 6. 첨부파일은 object storage에 둔다

Git에 큰 파일을 직접 넣지 않는다. DB에는 object key, 파일명, 크기, 해시 같은 메타데이터를 저장한다.

## 7. 공개 문서와 운영 기록을 분리한다

실제 서버 경로, 요청 ID, 백업 파일명, 개인 도메인, credential 정보는 public 문서에 두지 않는다.
