import argparse
import json
import logging
from pathlib import Path

from pydantic import ValidationError

from saba.schema import validate_articles


def validate_file(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError:
        logging.error("입력 파일 / 인코딩: UTF-8로 읽을 수 없습니다.")
        return 1
    except OSError as exc:
        logging.error("입력 파일 / 읽기: %s (OS 오류 코드 %s)", type(exc).__name__, exc.errno)
        return 1

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logging.error("JSON / %s행 %s열: %s", exc.lineno, exc.colno, exc.msg)
        return 1

    if not isinstance(data, list):
        logging.error("$ / 최상위 구조: 기사 객체 배열이 필요합니다.")
        return 1
    if not data:
        logging.error("$ / 최상위 배열: 빈 배열은 허용하지 않습니다.")
        return 1
    try:
        articles = validate_articles(data)
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_context=False, include_url=False):
            location = "$" + "".join(
                f"[{part}]" if isinstance(part, int) else f".{part}"
                for part in error["loc"]
            )
            logging.error("%s: %s", location, error["msg"])
        return 1
    except ValueError as exc:
        logging.error("%s", exc)
        return 1
    logging.info("JSON 검증 성공: 유효한 기사 %s건", len(articles))
    logging.info("검증만 수행했습니다. 수집·저장·분석·발송은 수행하지 않았습니다.")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="SABA 기본 실행 및 가상 뉴스 JSON 검증")
    parser.add_argument("--validate-json", type=Path, metavar="FILE", help="UTF-8 기사 배열 JSON 검증")
    args = parser.parse_args()
    if args.validate_json is not None:
        return validate_file(args.validate_json)
    logging.info("SABA 실행을 시작합니다.")
    logging.info("현재는 기본 실행 골격입니다. 외부 연결과 실제 메일 발송 기능은 없으며 수행하지 않습니다.")
    logging.info("SABA 실행을 정상 종료합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
