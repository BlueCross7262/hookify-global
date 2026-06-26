# PATCHES.md — hookify-global 변경 고지

본 문서는 Apache License 2.0 §4(b)의 변경 고지(Notice of Modification) 역할을 한다.
hookify-global 은 Anthropic 의 hookify 플러그인을 fork 하여 결정적 패치로 개선한 배포본이며,
**Anthropic 의 공식 플러그인이 아니다.**

## upstream 출처
- 레포: https://github.com/anthropics/claude-plugins-official
- 경로: `plugins/hookify`
- 추적 방식: git submodule + sparse-checkout(cone, `plugins/hookify` 만 실체화), `branch = main`
- 고정 SHA(pinned): `578b490d4bba80630e65880fc938fe6a78894244`
  - 현재 SHA 는 레포 루트 `UPSTREAM_SHA` 및 submodule gitlink 에 기록된다.

## fork 목적
원본 hookify 는 (1) 전역 규칙 미지원, (2) Windows/한글 UTF-8 인코딩 문제, (3) 읽기 도구 오발동,
(4) 차단 사유 미전달, (5) 훅 커맨드 공백 경로 문제가 있다. hookify-global 은 원본을 훼손하지 않고
`patches/` 의 결정적 diff 로만 이를 개선해, upstream 변경 후에도 재적용·충돌 해소가 쉽도록 한다.

## 변환 원칙
- 변환의 진실 원천은 `patches/` 의 `.patch` 파일이다. `dist/` 를 손으로 고치지 않는다.
- `dist/` 는 `build.py` 가 staging 에 패치를 적용해 결정적으로 생성한 배포 본체다.
- 패치 경로는 hookify 루트 상대(`a/core/...`, `b/hooks/...`)이며 개행은 LF 로 고정한다.

## 전역 vs 프로젝트 규칙 — override 가 아니라 합산(additive)
전역 규칙(`~/.claude/hookify.*.global.md`)과 프로젝트 규칙(`.claude/hookify.*.local.md`)은
**같은 이름이라도 서로 override 하지 않고 둘 다 발동한다(additive).** 단, `os.path.realpath` 가
동일한 실제 경로는 한 번만 로드해 이중 로드를 방지한다(예: 심볼릭 링크).

## 패치 목록

### 01-utf8-encoding.patch (P0)
- **변경 파일**: `core/config_loader.py`, `core/rule_engine.py`
- **의도**: 규칙 파일·트랜스크립트를 `encoding='utf-8'` 로 연다.
- **근거**: Windows 기본 인코딩(cp949 등)에서 이모지(⚠️)·한글이 깨지거나 `UnicodeDecodeError` 로 로드 실패한다.
- **수용 기준**: 이모지+한글 규칙 파일이 정상 로드되고 메시지가 보존된다.

### 02-py38-annotations.patch (P0)
- **변경 파일**: `core/config_loader.py`
- **의도**: docstring 직후, 다른 import 보다 앞에 `from __future__ import annotations` 를 추가한다.
- **근거**: `extract_frontmatter` 의 `tuple[Dict[str, Any], str]` 반환 애너테이션이 Python 3.8 런타임에서 평가 실패한다. 애너테이션을 문자열로 지연 평가해 import 를 성공시킨다.
- **수용 기준**: Python 3.8 에서 `import core.config_loader` 가 성공한다.

### 03-hook-execform.patch (무효화 — 0바이트, 회귀 환원)
- **상태**: 0바이트(빈 패치). `build.py` 가 0바이트 패치를 건너뛰므로 `hooks/hooks.json` 은 upstream 의 quoted shell-form 을 그대로 유지한다. `EXPECTED_PATCHES` 6슬롯 구조 보존을 위해 파일명만 남긴다.
- **원래 의도(폐기)**: 4개 이벤트(PreToolUse·PostToolUse·Stop·UserPromptSubmit) 훅을 shell form 에서 exec form(`command`+`args`)으로 전환하려 했다.
- **회귀 사유**: exec form 은 shell 없이 바이너리를 직접 spawn 한다(Node `child_process.spawn(shell:false)`). Windows 에서 `python3` 는 `.cmd` shim(`python3.cmd → python.exe`)이라 shell 없이는 실행되지 않아, 모든 훅 이벤트(매 도구 호출·프롬프트 제출)마다 exit 9009 / stderr `Python` 으로 실패했다 — 사용자에게 "Failed with non-blocking status code: Python" 로 노출.
- **재현 증거**: `spawnSync('python3', [...], {shell:false})` → status 9009 / stderr "Python"; `{shell:true}` → status 0. upstream 및 타 플러그인은 전부 shell-form 이라 무영향.
- **공백 경로**: upstream 의 `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/X.py"` 가 이미 `"..."` 따옴표로 방어하므로 별도 패치 불필요. (원래 patch 03 이 풀려던 문제는 upstream 에 이미 없었다.)
- **수용 기준**: dist·캐시의 hooks.json 이 shell-form(`args` 없음)이고, 하네스가 shell 경유로 훅을 정상 실행(exit 0)한다.

### 04-global-rules-dedup.patch (P1, 본래 목표)
- **변경 파일**: `core/config_loader.py`
- **의도**: `load_rules()` 가 프로젝트 글롭(`.claude/hookify.*.local.md`)과 전역 글롭(`~/.claude/hookify.*.global.md`)을 모두 수집한다. 프로젝트 먼저·전역 나중, 각 글롭은 정렬, `os.path.realpath` 기준 중복 제거.
- **근거**: 전역 규칙을 임의 프로젝트에 적용하기 위함.
- **수용 기준**: 전역 규칙이 임의 프로젝트에 적용되고, 같은 파일이 두 번 로드되지 않는다(합산 의미는 위 참조).

### 05-read-event.patch (P1)
- **변경 파일**: `hooks/pretooluse.py`, `hooks/posttooluse.py`, `core/rule_engine.py`
- **의도**: `Read`·`Glob`·`Grep`·`LS` 를 `read` 이벤트로 매핑하고, `_extract_field` 가 읽기 전용 경로를 추출한다(`Read`=`file_path`, `LS`=`path`, `Glob`/`Grep`=`path` 가 있을 때만, `pattern` 은 경로로 보지 않음).
- **근거**: `event: file` 규칙이 Read/Glob/Grep/LS 에서 오발동하던 문제 차단. 공식 PreToolUse 입력 스키마(Read=file_path, Glob/Grep=pattern+path 선택)와 일치.
- **수용 기준**: `event: file` 규칙이 Read/Glob/Grep/LS 에서 미발동, Edit/Write 에서는 발동. Glob 에 `path` 가 없으면 무크래시.

### 06-block-reason.patch (P1)
- **변경 파일**: `core/rule_engine.py`
- **의도**: 차단 응답을 이벤트별로 분기한다. PreToolUse 는 `hookSpecificOutput.permissionDecision="deny"` + `permissionDecisionReason`, PostToolUse·Stop·UserPromptSubmit 는 top-level `decision: "block"` + `reason`.
- **근거**: 공식 문서상 PreToolUse 만 `hookSpecificOutput` 차단 경로를 쓰고, 나머지 차단 이벤트는 top-level `decision`/`reason` 을 쓴다. 모델에 차단 사유를 정확히 전달한다.
- **수용 기준**: PreToolUse 차단엔 `permissionDecisionReason`, Post·Stop·UserPromptSubmit 차단엔 top-level `reason`.

### 07-commands-global-rules.patch (P1)
- **변경 파일**: `commands/list.md`, `commands/configure.md`
- **의도**: 두 슬래시 명령(`/hookify:list`·`/hookify:configure`)이 프로젝트 규칙(`.claude/hookify.*.local.md`)뿐 아니라 전역 규칙(`~/.claude/hookify.*.global.md`)도 Glob 으로 수집하도록 한다. 두 명령의 `allowed-tools` 에 Bash 가 없어 `~` 셸 확장이 불가하므로, 해소된 절대 홈 `.claude` 경로를 Glob 의 `path` 인자로 넘긴다.
- **근거**: 런타임 로더(`load_rules`, patch 04)는 이미 전역 규칙을 로드하지만, list·configure 명령은 로컬만 글롭해 전역 규칙이 목록·토글에서 누락됐다.
- **수용 기준**: dist `commands/list.md`·`commands/configure.md` 가 전역 글롭(`hookify.*.global.md` + 홈 `.claude` 의 `path`)을 지시한다.

## 라이선스
- 원본·본 fork 모두 Apache License 2.0. 레포 루트와 `dist/` 양쪽에 `LICENSE` 를 포함한다.
- Anthropic 상표나 "official" 표기를 사칭하지 않는다.
