import argparse
import json
import logging
from pathlib import Path
import sqlite3

from pydantic import ValidationError

from saba.schema import Article, validate_articles
from saba.storage import DEFAULT_DB, StorageError, get_article, list_articles, save_articles


def read_articles(path: Path) -> list[Article] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError:
        logging.error("입력 파일 / 인코딩: UTF-8로 읽을 수 없습니다.")
        return None
    except OSError as exc:
        logging.error("입력 파일 / 읽기: %s (OS 오류 코드 %s)", type(exc).__name__, exc.errno)
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logging.error("JSON / %s행 %s열: %s", exc.lineno, exc.colno, exc.msg)
        return None

    if not isinstance(data, list):
        logging.error("$ / 최상위 구조: 기사 객체 배열이 필요합니다.")
        return None
    if not data:
        logging.error("$ / 최상위 배열: 빈 배열은 허용하지 않습니다.")
        return None
    try:
        articles = validate_articles(data)
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_context=False, include_url=False):
            location = "$" + "".join(
                f"[{part}]" if isinstance(part, int) else f".{part}"
                for part in error["loc"]
            )
            logging.error("%s: %s", location, error["msg"])
        return None
    except ValueError as exc:
        logging.error("%s", exc)
        return None
    return articles


def validate_file(path: Path) -> int:
    articles = read_articles(path)
    if articles is None:
        return 1
    logging.info("JSON 검증 성공: 유효한 기사 %s건", len(articles))
    logging.info("검증만 수행했습니다. 수집·저장·분석·발송은 수행하지 않았습니다.")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="SABA 기본 실행, JSON 검증 및 SQLite 기사 저장·조회")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--validate-json", type=Path, metavar="FILE", help="UTF-8 기사 배열 JSON 검증")
    actions.add_argument("--import-json", type=Path, metavar="FILE", help="검증 후 SQLite에 기사 저장")
    actions.add_argument("--list-articles", action="store_true", help="저장 기사 목록 조회")
    actions.add_argument("--show-article", metavar="ID", help="기사 한 건의 전체 JSON 조회")
    parser.add_argument("--db", type=Path, metavar="PATH", help="SQLite DB 경로 (기본: 프로젝트 루트/data/saba.db)")
    args = parser.parse_args()
    storage_action = args.import_json is not None or args.list_articles or args.show_article is not None
    if args.db is not None and not storage_action:
        parser.error("--db는 저장 또는 조회 옵션과 함께 사용해야 합니다.")
    if args.show_article is not None and not args.show_article.strip():
        parser.error("--show-article에는 비어 있지 않은 ID가 필요합니다.")
    if args.validate_json is not None:
        return validate_file(args.validate_json)
    if storage_action:
        path = args.db if args.db is not None else DEFAULT_DB
        try:
            if args.import_json is not None:
                articles = read_articles(args.import_json)
                if articles is None:
                    return 1
                inserted, skipped = save_articles(path, articles)
                logging.info("기사 저장 완료: 신규 %s건 · 동일 데이터 %s건 생략", inserted, skipped)
                logging.info("JSON 입력만 저장했습니다. 실제 뉴스 수집·AI 분석·발송은 수행하지 않았습니다.")
            elif args.list_articles:
                articles = list_articles(path)
                print(f"저장 기사 {len(articles)}건")
                for article in articles:
                    published = article.published_at.isoformat() if article.published_at else "미확인"
                    print(f"{article.article_id} | {article.original_title} | {article.source_name} | {published}")
            else:
                article = get_article(path, args.show_article)
                print(article.model_dump_json(indent=2))
        except StorageError as exc:
            logging.error("%s", exc)
            return 1
        except sqlite3.Error as exc:
            logging.error(
                "SQLite 저장·조회 실패: %s. DB 경로·접근 권한·잠금·파일 손상을 확인하세요.",
                getattr(exc, "sqlite_errorname", type(exc).__name__),
            )
            return 1
        except OSError as exc:
            logging.error("DB 경로 접근 실패: %s (OS 오류 코드 %s)", type(exc).__name__, exc.errno)
            return 1
        return 0
    logging.info("SABA 실행을 시작합니다.")
    logging.info("현재는 기본 실행 골격입니다. 외부 연결과 실제 메일 발송 기능은 없으며 수행하지 않습니다.")
    logging.info("SABA 실행을 정상 종료합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
