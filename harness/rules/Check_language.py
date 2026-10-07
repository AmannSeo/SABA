#!/usr/bin/env python3
"""모델이 작성한 출력에 한국어/영어 외의 문자가 있는지 검사한다.

사용법:
    python check_language.py report.md
    cat report.md | python check_language.py

종료 코드: 0 = 위반 없음, 1 = 위반 있음, 2 = 입력 오류

허용 목록 방식:
    - 글자(알파벳, 한글 등)는 Hangul 또는 Latin 문자만 허용한다.
    - 숫자, 공백, 문장부호, 기호, 이모지는 글자가 아니므로 검사하지 않는다.

검사에서 제외하는 영역 (Prompt_validation.md 2.3 원문 표기 규약):
    - 코드 블록(```)과 인라인 코드(`)
    - URL
    - 줄 맨 앞이 [원문] 으로 시작하는 줄

한계:
    - 영문 철자를 쓰는 다른 언어(예: 스페인어)는 구분하지 못한다.
      그 부분은 모델의 직접 점검으로 보완한다.
"""
import re
import sys
import unicodedata

ALLOWED_SCRIPTS = ("HANGUL", "LATIN")

FENCE = re.compile(r"^\s*```")
INLINE_CODE = re.compile(r"`[^`]*`")
URL = re.compile(r"https?://\S+")
SOURCE_MARK = "[원문]"


def is_allowed(ch):
    """글자가 아니면 통과. 글자면 Hangul 또는 Latin 만 통과."""
    if not ch.isalpha():
        return True
    name = unicodedata.name(ch, "")
    return name.startswith(ALLOWED_SCRIPTS)


def check(text):
    """위반 목록 [(줄 번호, 문자, 문자 이름, 줄 내용)] 을 돌려준다."""
    violations = []
    in_fence = False

    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith(SOURCE_MARK):
            continue

        cleaned = URL.sub("", INLINE_CODE.sub("", line))
        for ch in cleaned:
            if not is_allowed(ch):
                violations.append((number, ch, unicodedata.name(ch, "UNKNOWN"), line.strip()))
    return violations


def main():
    if len(sys.argv) > 2:
        print("사용법: check_language.py [파일]", file=sys.stderr)
        return 2
    try:
        if len(sys.argv) == 2:
            with open(sys.argv[1], encoding="utf-8") as f:
                text = f.read()
        else:
            text = sys.stdin.read()
    except OSError as e:
        print(f"입력을 읽을 수 없습니다: {e}", file=sys.stderr)
        return 2

    violations = check(text)
    if not violations:
        print("OK: 한국어/영어 외 문자가 발견되지 않았습니다.")
        return 0

    print(f"FAIL: {len(violations)}개 위반")
    for number, ch, name, line in violations[:50]:
        print(f"  줄 {number}: '{ch}' ({name})  |  {line[:80]}")
    if len(violations) > 50:
        print(f"  ... 외 {len(violations) - 50}개")
    return 1


if __name__ == "__main__":
    sys.exit(main())