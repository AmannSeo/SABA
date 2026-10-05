import logging


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.info("SABA 실행을 시작합니다.")
    logging.info("현재는 기본 실행 골격입니다. 외부 연결과 실제 메일 발송 기능은 없으며 수행하지 않습니다.")
    logging.info("SABA 실행을 정상 종료합니다.")
