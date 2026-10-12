"""SABA.exe 진입점 (D-069). "SABA.exe -m 모듈 인자" 를 "python -m 모듈 인자" 와 같게 실행한다.

작업 스케줄러·관리 페이지가 쓰는 [sys.executable, "-m", ...] 명령이 실행 파일에서도 그대로 동작한다.
"""

import os
import runpy
import sys

USAGE = """사용법: SABA.exe -m <모듈> [인자]
  -m saba.admin              관리 컨트롤 페이지 시작 (--stop 종료)
  -m saba.daily --run        오늘 분량 실행 (수집 → 분석 → 메일 → 발송)
  -m saba.daily --register   자동 실행 등록 명령 확인 (--unattended, --apply)
  -m saba.deploy --backup    data\\·config\\ 백업
  -m saba.send_mail          발송 드라이런"""

if __name__ == "__main__":
    # 실행 파일은 PYTHONIOENCODING 을 읽지 않는다. 관리 페이지·saba.ps1 이 UTF-8 로 읽을 수 있게 직접 맞춘다.
    if os.environ.get("PYTHONIOENCODING"):
        for stream in (sys.stdout, sys.stderr):
            stream.reconfigure(encoding=os.environ["PYTHONIOENCODING"])
    if len(sys.argv) < 3 or sys.argv[1] != "-m" or not sys.argv[2].split(".")[0] == "saba":
        print(USAGE)
        raise SystemExit(2)
    module = sys.argv[2]
    sys.argv = [sys.argv[0], *sys.argv[3:]]
    runpy.run_module(module, run_name="__main__", alter_sys=True)
