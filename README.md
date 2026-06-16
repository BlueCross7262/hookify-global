# hookify-global

Anthropic [hookify](https://github.com/anthropics/claude-plugins-official) 플러그인을 fork 하여
**전역 규칙·UTF-8·읽기 이벤트 분리·차단 사유·exec form 훅** 을 개선한 Claude Code 플러그인이다.

> ⚠️ **비사칭 고지** — 본 플러그인은 **Anthropic 의 공식 플러그인이 아니다.** Apache License 2.0 에 따른 비공식 fork 이며, 변경 내역은 [`PATCHES.md`](./PATCHES.md) 에 고지한다.

## ⚠️ 원본 hookify 와 동시 활성화 경고
본 fork 와 원본 hookify 를 함께 켜면 같은 `~/.claude`·프로젝트 규칙 파일을 양쪽이 읽어 **훅이 이중으로 발동된다.**
본 fork 사용 시 원본 hookify 를 비활성화하라:

```text
/plugin disable hookify
```

## 설치

> 엔드유저는 이 섹션만 보면 된다. 빌드·patch·submodule 은 아래 [개발자용](#빌드) 섹션을 참조하라.

**사전 요구사항** — [Claude Code](https://docs.claude.com/en/docs/claude-code) CLI.

1. 마켓플레이스 등록 (GitHub `owner/repo` 단축형):

   ```text
   /plugin marketplace add BlueCross7262/hookify-global
   ```

   특정 브랜치·태그로 고정하려면 `@ref` 를 붙인다 (`BlueCross7262/hookify-global@main`). 단축형 대신 전체 git URL 로도 등록할 수 있다: `/plugin marketplace add https://github.com/BlueCross7262/hookify-global.git`.

2. 플러그인 설치:

   ```text
   /plugin install hookify-global@hookify-global-marketplace
   ```

   마켓플레이스 등록만으로는 설치되지 않는다 — 위 두 단계를 모두 실행해야 한다.

3. 원본 hookify 비활성화 — 본 fork 와 원본을 동시에 켜면 훅이 이중 발동한다 (상단의 *동시 활성화 경고* 참조). 비활성화: `/plugin disable hookify`.

4. 설치 확인 — `/plugin` 의 Installed 탭에서 `hookify-global` 항목과 로드 오류 유무를 확인한다.

> `hookify-global` 이 마켓플레이스에서 안 보이거나 "plugin not found" 가 뜨면 캐시가 오래된 것이다. `/plugin marketplace update hookify-global-marketplace` 로 갱신 후 재설치한다.
>
> `dist/` 가 레포에 커밋되어 있어 빌드 없이 설치된다. 단 `marketplace.json` 의 `source: "./dist"` 상대경로는 git/디렉터리 마켓플레이스에서만 풀리므로, 위처럼 `owner/repo` 단축형이나 전체 git URL 로 등록해야 한다 — `marketplace.json` 만 단독 URL 로 가리키면 상대경로가 풀리지 않는다.

## 전역 규칙 사용법
- **전역 규칙** — `~/.claude/hookify.<name>.local.md` — 모든 프로젝트에 적용된다.
- **프로젝트 규칙** — `.claude/hookify.<name>.local.md` — 해당 프로젝트에만 적용된다.
- 동일 이름이라도 **override 없이 둘 다 적용된다(additive).** 단, 같은 실제 경로(realpath)는 한 번만 로드된다.

최소 예시 — `~/.claude/hookify.no-force-push.local.md`:

```markdown
---
name: no-force-push
enabled: true
event: bash
action: warn
conditions:
  - field: command
    operator: regex_match
    pattern: git\s+push\s+.*--force
---
⚠️ force push 감지 — 정말 강제 푸시할 것인가?
```

이 파일을 홈 `~/.claude/` 에 두면 모든 프로젝트의 Bash `git push --force` 에서 경고가 발동한다.

## upstream 추적
- 원본은 git submodule + sparse-checkout(cone)로 `plugins/hookify` 만 실체화해 추적한다.
- 추적 브랜치는 `main`, 고정 SHA 는 `UPSTREAM_SHA` 에 기록된다.

## 빌드
표준 라이브러리만 사용한다(외부 Python 의존성 0).

```bash
python3 build.py             # dist/ 산출
python3 build.py --install   # dist 산출 후 캐시로 복사 설치(seed/캐시 검증용)
python3 build.py --update    # upstream 갱신 후 빌드
```

`dist/` 가 곧 배포되는 플러그인 본체다. `dist/` 를 손으로 고치지 말고, 개선은 `patches/` 의 결정적 patch 로만 관리한다.

## 개발 테스트
개발 반복 루프는 인플레이스 로드를 쓴다(항상 최신, 캐시 staleness 회피).

```bash
claude --plugin-dir ./dist
```

로드 확인은 `claude --debug` 의 "loading plugin" 메시지로 한다.

## 검증

```bash
claude plugin validate ./dist   # 플러그인(plugin.json + hooks.json + frontmatter)
claude plugin validate .        # marketplace.json
```

`claude` CLI 가 없으면 검증은 skip 한다.

## 네이티브 Windows override
기본 훅 인터프리터는 `python3`(exec form)이다. WSL2 가 아닌 네이티브 Windows 에서는
`patches/03-hook-execform.patch` 의 `command` 를 `py`, `args` 를 `["-3", "${CLAUDE_PLUGIN_ROOT}/hooks/<event>.py"]` 로
바꾸고 `python3 build.py` 로 재빌드한다. dist/캐시 수동 수정은 임시 테스트용으로만 쓰고 커밋하지 않는다.

## 두 번째 머신(Tailscale 듀얼머신)

```bash
git clone --recursive <repo>
cd hookify-global
git submodule update --init
python3 build.py
```

## 라이선스
Apache License 2.0. 레포 루트와 `dist/` 양쪽에 [`LICENSE`](./LICENSE) 를 포함한다. 변경 고지는 [`PATCHES.md`](./PATCHES.md) 를 참조하라.
