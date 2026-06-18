# AI 러너 전환 계획

이 문서는 Codex CLI runner와 OpenAI API runner를 함께 운영하기 위한 계획이다.

## 목적

- ChatGPT 로그인 기반 Codex CLI를 유지한다.
- 필요한 경우 OpenAI API를 일부 기능에 사용한다.
- 비용, 품질, 안정성을 비교해 점진적으로 전환한다.

## 러너 종류

| Runner | 용도 |
| --- | --- |
| `dry-run` | 개발/검증용 placeholder |
| `codex-cli` | 기본 AI 처리 runner |
| `openai-api` | API key 기반 선택 runner |
| `rules` | 대화 답변 provider fallback |

## OpenAI API 사용 원칙

- API key는 server-only secret file 또는 `.env`에 둔다.
- 공개 문서나 runner 로그에는 key 값을 남기지 않는다.
- one-shot smoke가 통과하기 전에는 상시 worker 기본값으로 쓰지 않는다.
- 대화 답변 provider는 검색/근거 결정과 분리한다.

## 점검 항목

- API key 파일이 컨테이너에서 읽히는지 확인한다.
- smoke 요청이 성공하는지 확인한다.
- worker worktree가 남지 않는지 확인한다.
- 실패 시 Codex CLI 또는 rules provider로 되돌릴 수 있어야 한다.
