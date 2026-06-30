#!/usr/bin/env python3
"""hookify-global 결정적 빌드 스크립트.

upstream/plugins/hookify(submodule, sparse-checkout)를 임시 staging으로 복사하고
patches/의 결정적 패치를 순서대로 적용해 dist/를 산출한다.
외부 Python 의존성 없이 표준 라이브러리만 사용한다(git CLI 호출은 허용).

사용법:
    python3 build.py             # dist 산출
    python3 build.py --install   # dist 산출 후 캐시로 복사 설치(seed/캐시 검증용)
    python3 build.py --update    # upstream remote update 후 빌드
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
UPSTREAM = REPO / "upstream" / "plugins" / "hookify"
PATCHES_DIR = REPO / "patches"
DIST = REPO / "dist"

MARKETPLACE_NAME = "hookify-global-marketplace"
PLUGIN_NAME = "hookify-global"
PLUGIN_VERSION = "0.1.0-global.7"
AUTHOR_NAME = "주인"
PLUGIN_DESCRIPTION = (
    "Anthropic hookify 기반 전역 규칙·UTF-8·읽기 이벤트·차단 사유 개선 fork"
)

EXPECTED_PATCHES = [
    "01-utf8-encoding.patch",
    "02-py38-annotations.patch",
    "03-hook-execform.patch",
    "04-global-rules-dedup.patch",
    "05-read-event.patch",
    "06-block-reason.patch",
    "07-commands-global-rules.patch",
    "08-cwd-scope.patch",
    "09-cwd-path-scope.patch",
]

VERSION_RE = re.compile(r"^0\.1\.0-global\.\d+$")
TEXT_SUFFIX = {".py", ".json", ".md"}


def die(msg: str, code: int = 1) -> None:
    print(f"[build:오류] {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str) -> None:
    print(f"[build] {msg}")


def warn(msg: str) -> None:
    print(f"[build:경고] {msg}", file=sys.stderr)


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), check=check,
        capture_output=True, text=True, encoding="utf-8",
    )


def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def normalize_lf(root: Path) -> None:
    """텍스트 파일의 개행을 LF로 정규화한다.

    로컬 autocrlf 설정과 무관하게 staging을 upstream 정본(LF)으로 고정해
    LF 컨텍스트 패치가 Windows/WSL2 양쪽에서 결정적으로 적용되게 한다.
    """
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in TEXT_SUFFIX:
            b = p.read_bytes()
            if b"\r\n" in b:
                p.write_bytes(b.replace(b"\r\n", b"\n"))


def verify_environment() -> None:
    if not (REPO / ".gitmodules").exists():
        die(".gitmodules 없음 — upstream submodule이 구성되지 않았다.")
    if not UPSTREAM.is_dir():
        die(f"{UPSTREAM} 없음 — 'git submodule update --init'를 먼저 실행하라.")
    r = run_git("-C", "upstream", "sparse-checkout", "list", check=False)
    if r.returncode == 0 and r.stdout.strip():
        info("sparse 대상: " + r.stdout.strip().replace("\n", ", "))


def update_submodule() -> None:
    info("upstream 갱신: git submodule update --remote --depth 1 upstream")
    run_git("submodule", "update", "--remote", "--depth", "1", "upstream")
    sha = run_git("-C", "upstream", "rev-parse", "HEAD").stdout.strip()
    (REPO / "UPSTREAM_SHA").write_text(sha + "\n", encoding="utf-8", newline="\n")
    info(f"UPSTREAM_SHA 갱신: {sha}")


def check_patch_integrity() -> None:
    actual = sorted(p.name for p in PATCHES_DIR.glob("*.patch"))
    if actual != EXPECTED_PATCHES:
        die(
            "패치 무결성 검증 실패(누락·여분·순서 불일치).\n"
            f"  기대: {EXPECTED_PATCHES}\n"
            f"  실제: {actual}"
        )
    info(f"패치 무결성 OK ({len(EXPECTED_PATCHES)}개)")


def apply_patches(staging: Path) -> None:
    for name in EXPECTED_PATCHES:
        patch = PATCHES_DIR / name
        if patch.stat().st_size == 0:
            warn(f"{name}: 0바이트 패치 — 건너뜀(방어)")
            continue
        r = subprocess.run(
            ["git", "-C", str(staging), "apply", str(patch)],
            capture_output=True, text=True, encoding="utf-8",
        )
        if r.returncode != 0:
            head = "\n".join(
                patch.read_text(encoding="utf-8", errors="replace").splitlines()[:40]
            )
            die(
                f"패치 적용 실패: {name}\n"
                f"--- 패치 첫 40줄 ---\n{head}\n"
                f"--- git apply stderr ---\n{r.stderr.strip()}\n"
                "기존 dist는 변경되지 않았다."
            )
        info(f"{name}: 적용됨")


def write_plugin_json(staging: Path) -> None:
    if not VERSION_RE.match(PLUGIN_VERSION):
        die(f"PLUGIN_VERSION 형식 위반: {PLUGIN_VERSION} (기대: 0.1.0-global.N)")
    data = {
        "name": PLUGIN_NAME,
        "version": PLUGIN_VERSION,
        "description": PLUGIN_DESCRIPTION,
        "author": {"name": AUTHOR_NAME},
        "license": "Apache-2.0",
    }
    meta_dir = staging / ".claude-plugin"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "plugin.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    info(f"plugin.json 생성(version={PLUGIN_VERSION})")


def copy_distribution_docs(staging: Path) -> None:
    """LICENSE·PATCHES.md를 레포 루트에서 staging 루트로 복사한다.

    설치 시 플러그인 디렉터리(dist)만 캐시로 복사되므로 Apache 준수상
    라이선스·변경 고지가 dist 안에 있어야 한다.
    """
    for fn in ("LICENSE", "PATCHES.md"):
        src = REPO / fn
        if src.exists():
            shutil.copy2(src, staging / fn)
            info(f"{fn} 포함")
        else:
            warn(f"{fn} 없음 — dist에 포함되지 않는다(레포 루트에 생성 필요).")


def build_staging(staging: Path) -> None:
    shutil.copytree(UPSTREAM, staging)
    normalize_lf(staging)
    apply_patches(staging)
    # git apply가 전역 core.autocrlf를 따라 패치 대상 파일에 CRLF를 재도입할 수 있으므로
    # 패치 적용 후 다시 LF로 정규화해 dist 산출물 개행을 결정적으로 고정한다.
    normalize_lf(staging)
    write_plugin_json(staging)
    copy_distribution_docs(staging)


def promote_to_dist(staging: Path) -> None:
    if DIST.exists():
        backup = REPO / f"dist.bak-{timestamp()}"
        DIST.rename(backup)
        info(f"기존 dist 백업: {backup.name}")
    shutil.copytree(staging, DIST, symlinks=False)
    info(f"dist 산출 완료: {DIST}")


def resolve_plugins_root() -> Path:
    env = os.environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR")
    if env:
        return Path(env)
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    if cfg:
        return Path(cfg) / "plugins"
    return Path.home() / ".claude" / "plugins"


def install_to_cache() -> None:
    symlinks = [p for p in DIST.rglob("*") if p.is_symlink()]
    if symlinks:
        die(f"dist에 symlink 존재(설치 금지): {[str(p) for p in symlinks]}")
    root = resolve_plugins_root()
    target = root / "cache" / MARKETPLACE_NAME / PLUGIN_NAME / PLUGIN_VERSION
    if target.exists():
        backup = target.parent / f"{PLUGIN_VERSION}.bak-{timestamp()}"
        target.rename(backup)
        info(f"기존 캐시 백업: {backup}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DIST, target, symlinks=False)
    info(f"설치 완료(복사): {target}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="hookify-global 결정적 빌드(dist 산출/설치/upstream 갱신)."
    )
    parser.add_argument("--install", action="store_true",
                        help="dist 산출 후 캐시 경로로 복사 설치한다.")
    parser.add_argument("--update", action="store_true",
                        help="upstream submodule을 원격에서 갱신한 뒤 빌드한다.")
    args = parser.parse_args()

    verify_environment()
    if args.update:
        update_submodule()
    check_patch_integrity()

    with tempfile.TemporaryDirectory(prefix="hookify-build-") as tmp:
        staging = Path(tmp) / "hookify"
        build_staging(staging)
        promote_to_dist(staging)

    if args.install:
        install_to_cache()

    info("빌드 완료")


if __name__ == "__main__":
    main()
