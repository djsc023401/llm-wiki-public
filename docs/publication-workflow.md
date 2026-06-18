# 공개 저장소 발행 방식

이 문서는 개발용 저장소와 공개 배포용 저장소를 분리해 운영하는 방식을 정리한다.

## 저장소 역할

| 저장소 | 용도 | 히스토리 정책 |
| --- | --- | --- |
| `OWNER/llm-wiki` | 개발용 저장소 | 기존 개발 히스토리를 유지한다. |
| `OWNER/llm-wiki-public` | 공개 배포용 저장소 | 공개 가능한 현재 스냅샷만 새 히스토리로 발행한다. |

공개 배포용 저장소에는 개발용 저장소의 전체 Git 히스토리를 push하지 않는다. 과거 커밋에는 운영 경로, 내부 구성, 실험 기록 같은 공개에 부적합한 정보가 있었을 수 있으므로, 현재 검증된 추적 파일만 새 저장소에 복사해 발행한다.

## 발행 원칙

1. 개발은 `OWNER/llm-wiki`에서 진행한다.
2. 공개 전 점검은 현재 작업 트리와 추적 파일 기준으로 수행한다.
3. `agent_private.md`, `.env`, key, backup, 개인 메모 데이터는 공개 스냅샷에 포함하지 않는다.
4. 공개 저장소는 snapshot commit만 갖는다.
5. 공개 저장소에 배포한 뒤 GitHub Actions가 통과하는지 확인한다.

## 공개 전 확인

```bash
git status --short
LLM_WIKI_PUBLIC_SCAN_TERMS="YOUR_REAL_DOMAIN
YOUR_INTERNAL_IP
YOUR_USER_HOME
YOUR_SECRET_PREFIX
YOUR_OWNER_NAME
YOUR_PRIVATE_NOTE_KEYWORD" python scripts/publication_gate.py
```

`LLM_WIKI_PUBLIC_SCAN_TERMS`의 검색어는 운영 환경에 맞는 실제 개인 도메인, 내부 IP 대역, 개인 홈 경로, token prefix, 저장소 owner, 개인 메모에 자주 등장하는 고유명으로 바꿔 실행한다. 실제 token, 내부 IP, 개인 도메인, private key, 개인화 설정 값, 실사용 메모가 나오면 공개 발행 전에 제거한다.

`scripts/publication_gate.py`는 작업 트리 상태, 추적 파일 공개 스캔, compile, pytest, 설치된 secret scanner를 한 번에 확인한다. `gitleaks`와 `trufflehog`가 반드시 설치되어 있어야 하는 환경에서는 `--secret-tools=require`를 추가한다.

공개 demo seed는 합성 데이터만 포함해야 한다. 전용 test DB를 준비한 환경에서는 공개 발행 전에 `tests/test_demo_seed.py`를 실행해 seed 생성, 재실행, 제안/일정 상태를 확인한다.

`git archive`는 추적 파일만 복사한다. 그래도 발행 전에는 `git ls-files`로 추적 대상에 `.env`, key, backup, `.codex-remote-attachments`, DB dump, object archive, 실사용 첨부파일이 없는지 확인한다.

## 스냅샷 발행 절차

아래 절차는 개발 저장소의 현재 `HEAD`를 임시 디렉터리에 복사해 새 Git 히스토리로 공개 저장소에 push한다.

```bash
tmpdir="$(mktemp -d)"
git archive --format=tar HEAD | tar -x -C "$tmpdir"

cd "$tmpdir"
git init
git add .
git commit -m "Publish public snapshot"
git branch -M main
git remote add origin https://github.com/OWNER/llm-wiki-public.git
git push -u origin main
```

이미 공개 저장소에 이전 스냅샷이 있고 전체를 현재 스냅샷으로 교체하려면 마지막 push에 `--force-with-lease`를 사용한다.

```bash
git push --force-with-lease origin main
```

공개 저장소는 snapshot-only 정책이므로 force push가 허용된다. 단, 공개 저장소에 외부 기여를 받을 계획이 생기면 이 정책을 재검토한다.

## 발행 후 확인

```bash
gh run list --repo OWNER/llm-wiki-public --branch main --limit 3
```

GitHub Actions가 성공하면 공개 발행이 완료된 것으로 본다.

새 설치 사용자가 demo seed를 선택적으로 실행할 수 있도록 공개 저장소의 설치 문서에서 `llm-wiki demo-seed` 명령이 보이는지도 확인한다.
