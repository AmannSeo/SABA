"""메일 작성자 정보 (머리말·인사말·서명). config/author.json 에 두고 관리 화면 설정에서 바꾼다 (2026-10-16 사용자 요청).

회사 홈페이지·주소와 서명 이미지 (sign/ 원본) 는 바꾸지 않는다.
"""

import json
from pathlib import Path
import re

AUTHOR_PATH = Path(__file__).resolve().parents[2] / "config" / "author.json"
# 이름: (화면 이름, 최대 길이, 필수)
FIELDS = {
    "name": ("이름", 20, True), "position": ("직급", 20, False), "english_name": ("영문 이름", 40, False),
    "division": ("본부", 30, False), "team": ("부서", 30, True), "greeting_team": ("인사말 부서 (비우면 부서)", 30, False),
    "mobile": ("휴대폰", 20, False),
    "email": ("이메일", 80, False),
}
DEFAULT = {"name": "서창현", "position": "선임", "english_name": "SEO changhyun", "division": "보안사업본부",
           "team": "SW보안사업팀", "greeting_team": "보안사업팀", "mobile": "010-3927-4628", "email": "ch.seo@tbell.co.kr"}
EMAIL = re.compile(r"[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+")
PHONE = re.compile(r"[0-9+()\- ]+")


class AuthorError(ValueError):
    """화면에 그대로 보여도 되는 안내 문구."""


def validate(data: dict) -> dict:
    author = {}
    for key, (label, limit, required) in FIELDS.items():
        value = " ".join(str(data.get(key) or "").split())
        if required and not value:
            raise AuthorError(f"{label} 을 입력하세요.")
        if len(value) > limit:
            raise AuthorError(f"{label} 은 {limit}자 이하로 입력하세요.")
        author[key] = value
    if author["email"] and not EMAIL.fullmatch(author["email"]):
        raise AuthorError("이메일 형식이 아닙니다.")
    if author["mobile"] and not PHONE.fullmatch(author["mobile"]):
        raise AuthorError("휴대폰은 숫자·-·+·괄호·공백만 쓸 수 있습니다.")
    return author


def load_author(path: Path = AUTHOR_PATH) -> dict:
    """파일이 없으면 기본값 (처음 설치·예전 백업 복원). 빠진 항목은 기본값으로 채운다."""
    if not path.exists():
        return dict(DEFAULT)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        raise AuthorError("config/author.json 형식이 올바르지 않습니다.") from None
    if not isinstance(data, dict):
        raise AuthorError("config/author.json 형식이 올바르지 않습니다.")
    return validate({**DEFAULT, **data})


def save_author(data: dict, path: Path = AUTHOR_PATH) -> dict:
    author = validate(data)
    path.write_text(json.dumps(author, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return author
