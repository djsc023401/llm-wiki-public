# 개발 전 준비 점검

이 문서는 새 환경에서 개발과 배포를 시작하기 전에 확인할 항목을 정리한다.

## 계정과 저장소

- GitHub 또는 source repository 접근 권한
- 서버 SSH 접근 권한
- 필요한 deploy key 또는 access token

## 서버

- Docker 실행 권한
- Docker Compose plugin
- reverse proxy와 HTTPS 인증서
- 충분한 디스크 공간
- 백업 저장 공간

## 설정 파일

- `deploy/llm-wiki-app/.env.example`을 복사한 server-only `.env`
- object storage credential
- AI runner credential

## 로컬 개발

- Python 3.12
- Git
- 테스트용 Postgres 또는 DB 테스트 skip 정책
- secret scanner

## 점검 명령

```bash
git status
python -m compileall src tests
python -m pytest
```

## 공개 문서 기준

실제 서버 주소, 개인 경로, 운영 도메인, 백업 파일명은 private notes에만 기록한다.
