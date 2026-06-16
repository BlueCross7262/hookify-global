---
name: hookify-rebuild
description: hookify-global fork에서 upstream 갱신 후 패치를 재적용하고 빌드·테스트·검증할 때 사용한다.
---

# hookify rebuild 절차

이 스킬은 hookify-global fork 유지보수용이다. upstream을 직접 수정하지 말고, 변경은 patches/의 결정적 patch로만 관리한다.

## 절차
1. `python3 build.py --update`를 실행한다.
2. 모든 패치가 적용되면 코드 수정 없이 테스트로 이동한다.
3. 패치 충돌 시 `PATCHES.md`의 의도·수용 기준을 읽고 현재 upstream 구조에 맞는 최소 변경으로 patch를 다시 생성한다.
4. `python3 -m unittest discover -s tests -p "test_*.py"`를 실행한다.
5. 가능하면 `claude plugin validate ./dist`와 `claude plugin validate .`를 실행하고, `claude --debug --plugin-dir ./dist -p "load smoke test"`로 로드를 확인한다. CLI가 없으면 skip 사유를 보고한다.
6. 통과하면 `build.py`의 `PLUGIN_VERSION`만 증가시키고 `python3 build.py`로 dist를 재생성한다(plugin.json 직접 수정 금지).
7. 변경 파일, upstream SHA, 테스트 결과, 충돌 해결 내용을 요약 보고한다.

## 쓰기 제한
- 허용: patches/, dist/, dist.bak-*/, UPSTREAM_SHA, build.py 버전 상수, 캐시 설치 경로.
- 금지: upstream/plugins/hookify 직접 수정, 관련 없는 홈 디렉터리 파일, dist 수동 패치.
