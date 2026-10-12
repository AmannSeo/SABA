"""부서 PC 이전용 데이터 백업·복원 (D-068). data/ 전체와 config/ 를 zip 하나로 옮긴다.

백업: python -m saba.deploy --backup            (backups/saba_backup_YYYYMMDD_HHMM.zip)
복원: python -m saba.deploy --restore <zip 경로>  (기존 data/·config/ 는 *_before_restore_시각 으로 보관)

환경 변수(Secret) 는 백업에 들어가지 않는다. 새 PC 에서 사용자가 직접 입력한다.
"""

import argparse
from datetime import datetime
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parents[2]
FOLDERS = ("data", "config")


class DeployError(Exception):
    pass


def backup(root: Path = ROOT, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    target = root / "backups" / f"saba_backup_{now:%Y%m%d_%H%M}.zip"
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder in FOLDERS:
            for path in sorted((root / folder).rglob("*")):
                if path.is_file() and path.name != "admin.pid":  # 실행 중 표시는 옮기지 않는다
                    archive.write(path, path.relative_to(root).as_posix())
    return target


def restore(archive_path: Path, root: Path = ROOT, now: datetime | None = None) -> list[str]:
    """zip 안 경로가 data/·config/ 아래가 아니면 아무것도 바꾸지 않고 거부한다."""
    now = now or datetime.now()
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        for name in names:
            parts = PurePosixPath(name).parts
            if not parts or parts[0] not in FOLDERS or ".." in parts or name.startswith("/") or ":" in name:
                raise DeployError(f"백업 파일에 허용되지 않은 경로가 있습니다: {name}")
        kept = []
        for folder in FOLDERS:
            current = root / folder
            if current.exists():
                moved = root / f"{folder}_before_restore_{now:%Y%m%d_%H%M%S}"
                current.rename(moved)
                kept.append(moved.name)
        archive.extractall(root)
    return kept


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--backup", action="store_true", help="data/ 와 config/ 를 backups/ 에 zip 으로 저장")
    group.add_argument("--restore", type=Path, metavar="ZIP", help="백업 zip 을 이 폴더에 복원")
    args = parser.parse_args()
    if args.backup:
        print(f"백업 완료: {backup()}")
        return 0
    try:
        kept = restore(args.restore)
    except (DeployError, zipfile.BadZipFile, OSError) as error:
        print(f"복원하지 않음: {error}")
        return 1
    print("복원 완료." + (f" 기존 폴더 보관: {', '.join(kept)}" if kept else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
