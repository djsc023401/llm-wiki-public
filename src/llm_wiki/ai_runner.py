from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import subprocess

from .prompts import (
    SourceNoteContext,
    build_codex_prompt,
    find_existing_source_note,
    first_nonempty_line,
    source_note_context,
)


@dataclass
class RunnerResult:
    summary: str
    changed_paths: list[str]


class AiRunner:
    def preflight(self, vault_path: Path) -> None:
        return None

    def run(self, request: dict, vault_path: Path) -> RunnerResult:
        raise NotImplementedError


class DryRunRunner(AiRunner):
    def run(self, request: dict, vault_path: Path) -> RunnerResult:
        source_path = vault_path / request["file_path"]
        text = request.get("content_snapshot") or source_path.read_text(encoding="utf-8")
        source_context = source_note_context(request, vault_path, text)
        title = source_context.title
        target = vault_path / source_context.target_path
        target.parent.mkdir(parents=True, exist_ok=True)
        summary = first_nonempty_line(text) or "요약할 본문이 없습니다."
        readable = _readable_rewrite(summary)
        if source_context.existing_path and target.exists():
            current = target.read_text(encoding="utf-8")
            update_block = "\n".join(
                [
                    "",
                    "## 처리 업데이트",
                    "",
                    f"- 요청: `{request['id']}`",
                    f"- 소스 파일: `{request['file_path']}`",
                    f"- 요약: {summary}",
                    f"- 읽기용 정리: {readable}",
                    "",
                ]
            )
            if f"- Request: `{request['id']}`" not in current:
                target.write_text(current.rstrip() + "\n\n" + update_block, encoding="utf-8")
            rel = target.relative_to(vault_path).as_posix()
            return RunnerResult(summary=f"Updated existing {rel}", changed_paths=[rel])
        target.write_text(
            "\n".join(
                [
                    "---",
                    f'title: "{title}"',
                    "type: source",
                    "status: draft",
                    "created: 2026-06-02",
                    "updated: 2026-06-02",
                    "source_kind: capture",
                    'source_url: ""',
                    "object_refs: []",
                    'content_hash: ""',
                    'media_type: "text/markdown"',
                    f'extracted_text: "{request["file_path"]}"',
                    "source_refs:",
                    f"  - {request['file_path']}",
                    "tags: []",
                    "---",
                    "",
                    f"# {title}",
                    "",
                    "## 읽기용 정리",
                    "",
                    readable,
                    "",
                    "## 요약",
                    "",
                    summary,
                    "",
                    "## 추출된 사실",
                    "",
                    "- 워크플로 검증을 위해 dry-run 러너가 생성한 항목입니다.",
                    "",
                    "## 소스 메타데이터",
                    "",
                    f"- 소스 파일: `{request['file_path']}`",
                    "",
                    "## 관련",
                    "",
                    "### 주제 제안",
                    "",
                    "| 후보 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- |",
                    "| 없음 |  |  | dry-run 출력에는 지원되는 주제 제안이 없습니다. |",
                    "",
                    "### 대상 제안",
                    "",
                    "| 후보 | 유형 | 제안 경로 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- | --- |",
                    "| 없음 |  |  |  | dry-run 출력에는 지원되는 대상 제안이 없습니다. |",
                    "",
                    "### 태그 제안",
                    "",
                    "| 후보 | 근거 | 검토 메모 |",
                    "| --- | --- | --- |",
                    "| 없음 |  | dry-run 출력에는 지원되는 태그 제안이 없습니다. |",
                    "",
                    "### 일정 제안",
                    "",
                    "| 후보 | 의도 | 유형 | 시작 | 종료 | 마감 | 알림 | 시간대 | 근거 | 검토 메모 |",
                    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
                    "| 없음 | 기록 전용 | reminder |  |  |  |  | Asia/Seoul |  | dry-run 출력에는 지원되는 일정 제안이 없습니다. |",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return RunnerResult(summary=f"Created {target.relative_to(vault_path).as_posix()}", changed_paths=[target.relative_to(vault_path).as_posix()])


class CodexCliRunner(AiRunner):
    def __init__(self, command: list[str] | None = None) -> None:
        self.command = command or shlex.split(os.getenv("CODEX_CLI_COMMAND", "codex"))
        self.exec_args = shlex.split(os.getenv("CODEX_CLI_EXEC_ARGS", ""))
        self.run_root = Path(os.getenv("CODEX_RUN_ROOT", "/data/codex-runs"))
        self.log_limit = int(os.getenv("CODEX_RUN_LOG_LIMIT_BYTES", "200000"))

    def preflight(self, vault_path: Path) -> None:
        result = subprocess.run(
            [*self.command, "login", "status"],
            cwd=vault_path,
            env=_codex_env(),
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"codex cli is not authenticated: {message}")

    def run(self, request: dict, vault_path: Path) -> RunnerResult:
        run_dir = self.run_root / request["id"]
        run_dir.mkdir(parents=True, exist_ok=True)
        run_dir.chmod(0o700)
        prompt, source_context = build_codex_prompt(request, vault_path)
        context = {
            "request_id": request["id"],
            "operation": request["operation"],
            "file_path": request["file_path"],
            "content_hash": request.get("content_hash"),
            "commit_sha": request.get("commit_sha"),
            "source_note": {
                "candidate_path": source_context.candidate_path,
                "existing_path": source_context.existing_path,
                "target_path": source_context.target_path,
            },
        }
        _write_private_text(run_dir / "prompt.md", prompt)
        _write_private_text(run_dir / "context.json", json.dumps(context, ensure_ascii=False, indent=2))
        result = subprocess.run(
            [*self.command, "exec", *self.exec_args, prompt],
            cwd=vault_path,
            env=_codex_env(),
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=1800,
            check=False,
        )
        _write_limited(run_dir / "stdout.txt", result.stdout, self.log_limit)
        _write_limited(run_dir / "stderr.txt", result.stderr, self.log_limit)
        if result.returncode != 0:
            raise RuntimeError(f"codex cli failed: {result.stderr[-1000:]}")
        return RunnerResult(summary="Codex CLI completed", changed_paths=[])


class OpenAIApiRunner(AiRunner):
    def __init__(self, *, client_factory=None, run_root: Path | None = None) -> None:
        self.enabled = _truthy_env("OPENAI_API_RUNNER_ENABLED")
        self.api_key = _secret_env("OPENAI_API_KEY", "OPENAI_API_KEY_FILE")
        self.model = os.getenv("OPENAI_API_MODEL")
        self.timeout_seconds = _int_env("OPENAI_API_TIMEOUT_SECONDS", 1800)
        self.max_output_tokens = _int_env("OPENAI_API_MAX_OUTPUT_TOKENS", 8192)
        self.reasoning_effort = os.getenv("OPENAI_API_REASONING_EFFORT", "low")
        self.client_factory = client_factory
        self.run_root = run_root or Path(os.getenv("OPENAI_API_RUN_ROOT", os.getenv("CODEX_RUN_ROOT", "/data/openai-api-runs")))

    def preflight(self, vault_path: Path) -> None:
        if not self.enabled:
            raise RuntimeError("openai-api runner is disabled; keep WORKER_RUNNER=codex-cli until API runner is explicitly enabled")
        if not self.api_key:
            raise RuntimeError("openai-api runner missing OPENAI_API_KEY or OPENAI_API_KEY_FILE")
        if not self.model:
            raise RuntimeError("openai-api runner missing OPENAI_API_MODEL")
        self._client()

    def run(self, request: dict, vault_path: Path) -> RunnerResult:
        run_dir = self.run_root / request["id"]
        run_dir.mkdir(parents=True, exist_ok=True)
        run_dir.chmod(0o700)
        prompt, source_context = build_codex_prompt(request, vault_path)
        api_input = _build_openai_api_input(prompt, request, source_context, vault_path)
        response = self._client().responses.create(
            model=self.model,
            input=[{"role": "user", "content": api_input}],
            reasoning={"effort": self.reasoning_effort},
            max_output_tokens=self.max_output_tokens,
            text={"format": _openai_file_plan_text_format(source_context.target_path)},
            metadata={
                "llm_wiki_request_id": request["id"],
                "llm_wiki_runner": "openai-api",
            },
        )
        status = getattr(response, "status", None)
        if status == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", "unknown")
            _write_private_json(run_dir / "response_metadata.json", _response_metadata(response))
            raise RuntimeError(f"openai-api response incomplete: {reason}")
        output_text = _response_output_text(response)
        plan = _parse_openai_file_plan(output_text)
        summary = _apply_openai_file_plan(plan, vault_path, source_context.target_path)
        _write_private_text(run_dir / "prompt.md", prompt)
        _write_private_json(
            run_dir / "context.json",
            {
                "request_id": request["id"],
                "operation": request["operation"],
                "file_path": request["file_path"],
                "content_hash": request.get("content_hash"),
                "commit_sha": request.get("commit_sha"),
                "source_note": {
                    "candidate_path": source_context.candidate_path,
                    "existing_path": source_context.existing_path,
                    "target_path": source_context.target_path,
                },
                "input_bytes": len(api_input.encode("utf-8")),
                "source_snapshot_bytes": len(str(request.get("content_snapshot") or "").encode("utf-8")),
            },
        )
        _write_private_json(run_dir / "response_metadata.json", _response_metadata(response))
        _write_private_json(
            run_dir / "applied_files.json",
            {
                "summary": summary,
                "files": [
                    {
                        "path": source_context.target_path,
                        "size_bytes": (vault_path / source_context.target_path).stat().st_size,
                    }
                ],
            },
        )
        return RunnerResult(summary=summary, changed_paths=[source_context.target_path])

    def _client(self):
        if self.client_factory:
            return self.client_factory(api_key=self.api_key, timeout_seconds=self.timeout_seconds)
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai-api runner missing OpenAI SDK dependency") from exc
        return OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)


def _build_openai_api_input(prompt: str, request: dict, source_context: SourceNoteContext, vault_path: Path) -> str:
    source_path = vault_path / request["file_path"]
    source_text = request.get("content_snapshot")
    if source_text is None and source_path.exists():
        source_text = source_path.read_text(encoding="utf-8")
    target_path = vault_path / source_context.target_path
    target_text = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    return "\n".join(
        [
            "You are generating a constrained file update for llm-wiki.",
            "",
            "Base task:",
            prompt,
            "",
            "Response contract:",
            "- Return JSON only. Do not wrap it in Markdown fences.",
            "- JSON shape: {\"summary\": string, \"files\": [{\"path\": string, \"content\": string}]}",
            f"- Return exactly one file entry for `{source_context.target_path}`.",
            "- The path must stay under `wiki/sources/` and must end with `.md`.",
            "- When existing target content is present, preserve human-authored sections unless the source directly requires a small update.",
            "- Do not include any API key, token, credential, or service secret.",
            "- Do not create or edit `wiki/topics/` or `wiki/entities/`; only suggest candidates in the source note.",
            "",
            f"Source file path: `{request['file_path']}`",
            "Source file content:",
            "```md",
            source_text or "",
            "```",
            "",
            f"Existing target source note path: `{source_context.target_path}`",
            "Existing target source note content:",
            "```md",
            target_text,
            "```",
        ]
    )


def _readable_rewrite(summary: str) -> str:
    summary = summary.strip() or "요약할 본문이 없습니다."
    return (
        f"이 소스는 원문 메모의 핵심 내용을 사람이 다시 읽기 쉽게 정리한 것입니다. "
        f"현재 확인되는 주요 내용은 {summary}입니다. 추가 맥락이나 불확실한 점은 "
        "AI 처리 결과의 요약, 추출된 사실, 관련 제안에서 함께 검토합니다."
    )


def _openai_file_plan_text_format(expected_target_path: str) -> dict:
    return {
        "type": "json_schema",
        "name": "llm_wiki_file_plan",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "files"],
            "properties": {
                "summary": {"type": "string"},
                "files": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["path", "content"],
                        "properties": {
                            "path": {"type": "string", "enum": [expected_target_path]},
                            "content": {"type": "string"},
                        },
                    },
                },
            },
        },
    }


def _parse_openai_file_plan(output_text: str) -> dict:
    try:
        plan = json.loads(output_text)
    except json.JSONDecodeError:
        stripped = output_text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise RuntimeError("openai-api response did not contain a JSON file plan") from None
        try:
            plan = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"openai-api response JSON could not be parsed: {exc}") from exc
    if not isinstance(plan, dict):
        raise RuntimeError("openai-api response JSON root must be an object")
    return plan


def _apply_openai_file_plan(plan: dict, vault_path: Path, expected_target_path: str) -> str:
    summary = str(plan.get("summary") or "OpenAI API completed").strip()
    files = plan.get("files")
    if not isinstance(files, list) or len(files) != 1:
        raise RuntimeError("openai-api response must contain exactly one file change")
    file_change = files[0]
    if not isinstance(file_change, dict):
        raise RuntimeError("openai-api file change must be an object")
    path = _validate_openai_output_path(file_change.get("path"), expected_target_path)
    content = file_change.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("openai-api file content must be a non-empty string")
    target = vault_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return summary or f"Updated {path}"


def _validate_openai_output_path(path: object, expected_target_path: str) -> str:
    if not isinstance(path, str):
        raise RuntimeError("openai-api file path must be a string")
    normalized = path.replace("\\", "/").strip().lstrip("/")
    if normalized != path.strip().replace("\\", "/").lstrip("/"):
        raise RuntimeError("openai-api file path contains unsupported whitespace")
    if normalized != expected_target_path:
        raise RuntimeError(f"openai-api file path {normalized} does not match expected target {expected_target_path}")
    if normalized.startswith("../") or "/../" in normalized or normalized == "..":
        raise RuntimeError("openai-api file path cannot contain parent-directory segments")
    if not normalized.startswith("wiki/sources/"):
        raise RuntimeError("openai-api file path must stay under wiki/sources/")
    if not normalized.endswith(".md"):
        raise RuntimeError("openai-api file path must be a Markdown file")
    return normalized


def _response_output_text(response) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    raise RuntimeError("openai-api response did not include output_text")


def _response_metadata(response) -> dict:
    return {
        "id": getattr(response, "id", None),
        "model": getattr(response, "model", None),
        "status": getattr(response, "status", None),
        "usage": _jsonable(getattr(response, "usage", None)),
        "incomplete_details": _jsonable(getattr(response, "incomplete_details", None)),
        "output_count": len(getattr(response, "output", []) or []),
    }


def _jsonable(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


def get_runner(name: str) -> AiRunner:
    if name == "codex-cli":
        return CodexCliRunner()
    if name == "openai-api":
        return OpenAIApiRunner()
    return DryRunRunner()


def _codex_env() -> dict[str, str]:
    allowed = [
        "CODEX_ACCESS_TOKEN",
        "CODEX_HOME",
        "HOME",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "LANG",
        "LC_ALL",
        "NO_PROXY",
        "NODE_EXTRA_CA_CERTS",
        "OPENAI_API_KEY",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
    ]
    return {name: os.environ[name] for name in allowed if os.environ.get(name)}


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _secret_env(name: str, file_name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    path = os.getenv(file_name)
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8").strip()
    return None


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid integer environment variable: {name}={value}") from exc
    if parsed < 1:
        raise RuntimeError(f"Invalid integer environment variable: {name}={value}; expected >= 1")
    return parsed


def _write_limited(path: Path, text: str, limit: int) -> None:
    encoded = text.encode("utf-8")
    if len(encoded) > limit:
        encoded = encoded[-limit:]
        prefix = f"[truncated to last {limit} bytes]\n".encode("utf-8")
        encoded = prefix + encoded
    path.write_bytes(encoded)
    path.chmod(0o600)


def _write_private_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def _write_private_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)
