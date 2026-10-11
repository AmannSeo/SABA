# SABA DEVELOPMENT STATUS

## 목적
SABA의 실제 구현 상태와 다음 작업을 저장소 기준으로 추적한다. 작업 시작 전 `PROJECT_RULES.md`, `harness/` 아래의 모든 규칙 파일, 현재 작업 경로에 적용되는 `AGENTS.md`를 읽고 적용한다.

## 현재 확인된 상태
### 현재 단계와 승인 상태
- 공식 개발 단계: 17단계 — 추가 Source 수집 (D-023~D-025)
- 17단계 구현: `src/saba/rss.py` Source 설정 표 (CERT-EU, KISA 보호나라 보안공지, CISA Advisories, The Hacker News, 보안뉴스). 시간대 없는 pubDate는 Source 설정의 한국 시간 기준 해석, 날짜만 있는 Source(보호나라)는 기본 수집 기간 48시간. `--collect-rss` 전체 Source 수집, Source별 실패·충돌 격리, `--source` 필터
- 17단계 첫 실제 저장 수집 (2026-10-07, `--collect-rss --bootstrap`, `data/saba.db` 신규): 5개 Source 모두 성공, 105건 저장 (CERT-EU 5, 보호나라 10, CISA 30, The Hacker News 30, 보안뉴스 30), 발행 시각 미확인 0건. The Hacker News·보안뉴스는 Source별 최대 30건 상한으로 각 20건 제외
- 17단계 검증: unittest 216개 중 215개 통과, 1개 Skip, 실패 0개. 테스트는 가상 Fixture 사용
- 17단계 후속 공식 RSS 묶음 (D-026): KISA 보호나라 보고서·가이드 채택 (승인 Source 6개). 취약점 정보는 게시 빈도 낮아 미채택, MSRC(2MiB 초과)·Google Security Blog(Atom)는 현재 구조로 수집 불가, Intel·AMD·NVIDIA는 공식 RSS 미확인. 검증: unittest 217개 중 216개 통과, 1개 Skip
- 같은 사건 중복 처리 (D-027): `src/saba/issues.py` group_issues() 순수 함수. CVE 공유 자동 묶음, 제품 키워드 + 3일 이내 후보 표시 (사람 확정), 요약 기사 제외, 공식 출처 우선 대표 기사. Source 설정에 official 표시 추가. 저장 기사 105건 기준 이슈 102개, 자동 묶음 3개, 후보 5쌍. Newsletter 반영·사람 확정 결과 보관은 미구현. 검증: unittest 227개 중 226개 통과, 1개 Skip
- 실제 수집 기사 비AI Newsletter Preview (D-028, D-029): `src/saba/issues.py` select_issues()·preview_article(), Source region 필드, `output/build_collected_preview.py` → `output/newsletter_preview_collected.html`. 기준 시각 2026-10-07 09:41 UTC: 기간 안 40건, 표시 이슈 19건 (국내 9, 해외 10, AI & Tech 0), Source 상한 제외 18건, 섹션 상한 제외 3건, 같은 사건 후보 1쌍. 가장 긴 카드 약 14,000자 (CISA 발췌, D-003 자동 절단 금지). 사용자 Preview 확인 전. 검증: unittest 232개 중 231개 통과, 1개 Skip
- Preview 보완 (D-030): 600자 초과 발췌 접기·펼치기 (내용 유지), AI 분석 전 AI & Tech 빈 섹션 안내 문구, 상한 유지. 사용자 Preview 확인 완료. 메일 앱 실제 표시는 미검증. 검증: unittest 234개 중 233개 통과, 1개 Skip
- 다음 작업 (D-031): 회사 메일 TEST 발송 설계. 설계안 제시 후 회사 환경 정보 확인 대기. 실제 발송은 미승인
- 메일 호환 HTML (D-032): `src/saba/mail.py` to_mail_html()·build_message(), `templates/email_signature.html`, `output/build_mail_preview.py` → `output/newsletter_mail_preview.html`·`.eml` (발송 없음). 실제 기사 19건 기준 메일 HTML 약 120KB, .eml 약 1.46MB (로고 원본 928KB 첨부). 메일 앱 실제 표시는 사용자가 .eml 을 열어 확인 필요. 실제 발송은 회사 메일 환경 정보 대기. 검증: unittest 243개 중 242개 통과, 1개 Skip
- .eml 확인 보완 (D-033): 메일에서 간략·자세히 보기 차례 표시, 브리핑 분야당 최대 5건, 출처 목록 말줄임, 서명 뉴스레터 폭 안 가운데 배치 구현. 실제 기사 AI 분석 연결 (`src/saba/briefing.py`, 분석 DB 저장·재사용, 대상 밖 제외, 중요도 미표시) 구현
- 실제 기사 AI 분석 1회 실행 결과 (2026-10-07): 신규 호출 15건, 유효 1건, 형식 검증 실패 13건 (11건 근거 인용문이 원문에 없음, 2건 근거 누락), 시간 초과 1건, 발췌 없음 4건 호출 안 함. 비용 약 $0.012 (누적 호출 27건, 약 $0.017). 현재 Preview·.eml 은 저장된 1건만 AI 표시, 나머지는 원문 발췌 대체. 근거 인용 방식 보완 결정 대기. 검증: unittest 250개 중 249개 통과, 1개 Skip
- AI 요약 보완 (D-034): 문장 번호 근거 방식, 모든 출력 한국어, 응답 대기 60초. 재분석 1회: 신규 14건 중 유효 3건 (누적 유효 4건), 실패 11건은 구조 문제 (제목·발췌에 걸친 번호 5, 잘못된 번호 3, 근거 누락 4). 이후 항목별 근거 번호 필수 Schema와 연속 구간 분할을 구현하고 Mock 검증 (재호출 없음, 추가 재분석 승인 대기). 누적 호출 41건 약 $0.024. Preview·.eml 은 저장 결과 4건 AI 한국어 제목·요약 표시. 검증: unittest 255개 중 254개 통과, 1개 Skip
- AI 요약 보완 2 (D-035): 항목별 근거 번호 Schema로 실제 재분석 1회: 신규 11건 중 유효 8건 (누적 유효 12건, 표시 19건 중 12건 AI 한국어 제목·요약). 실패 3건은 모두 CISA 긴 발췌(7.7~9.7천 자) 의 "근거 문장 번호 유효하지 않음" 이며, 실패 사유에 항목 이름과 종류(형식·비어 있음·범위 밖)를 기록하도록 보완 (내용 미기록, 재호출 없음). 보호나라 공지(발췌 없음) 4건은 제목만 표시 유지. 이번 비용 약 $0.0055, 누적 호출 52건 약 $0.030. 검증: unittest 255개 중 254개 통과, 1개 Skip
- 사용자 확인 문제 보완 (D-036): 브리핑 CSS 탭 전환·SAMPLE 형식 내용, 요약 최대 5문장·600자, 원문 발췌 버튼과 핵심 사실 상자 제거, 브라우저용 이미지 경로, 서명 PNG 첨부. 실제 재분석 1회: 신규 15건 중 유효 12건 (요약 3~4문장, CISA 5건 모두 성공), 실패 3건은 category 근거 번호 비어 있음 → 지시문 보완 (재호출 없음). 이번 비용 약 $0.0076, 누적 호출 67건 약 $0.037. 표시 19건 중 12건 AI 한국어 요약, 7건 (보호나라 4, 실패 3) 은 제목·출처만. 검증: unittest 257개 중 256개 통과, 1개 Skip
- D-037: 실패 3건만 재분석 1회 (신규 3건 모두 유효, 이번 비용 약 $0.001, 누적 호출 70건 약 $0.038). 표시 19건 중 15건 AI 한국어 제목·요약 (3~4문장), 보호나라 4건은 제목만. 로고 축소본은 사용자 제공 대기, 화면 재확인 대기. 검증: unittest 257개 중 256개 통과, 1개 Skip
- D-038: 발췌 없는 보호나라 공지 4건은 공지 페이지 본문을 GET 1회씩 가져와 (캐시 data/boho_bodies.json, 기사 DB 쓰기 없음, src/saba/notice_body.py) 본문 앞부분(최대 1200자)을 발췌로 AI 요약. 신규 4건 모두 유효, 이번 비용 약 $0.002, 누적 호출 74건 약 $0.040. 표시 19건 모두 AI 한국어 제목·요약. 요약 2건에 원문 한자 표기(U+793E) 포함 → 지시문에 한자 한글 변환 규칙 추가 (재호출 없음). 검증: unittest 260개 중 259개 통과, 1개 Skip
- D-039: 한자 표기 요약 2건만 재분석 1회 (기존 결과는 data/analysis_d038_backup.db 보관). 신규 2건 모두 유효했으나 지시문 규칙에도 회사 한자 표기(U+793E)가 그대로 나옴 → 지시문으로는 해결 안 됨 확인. 이번 비용 약 $0.001, 누적 호출 76건 약 $0.041. 로고 원본 유지. 사용자 의견: 시사점에 분석 내용 필요 (추후 단계). 검증: unittest 260개 중 259개 통과, 1개 Skip
- D-040: 회사 한자 표기(U+793E) 는 화면용 사본(briefing.display_result) 에서만 "사" 로 변경, 저장 결과·근거 인용 불변, 호출 없음. 메일 HTML 언어 검사는 서명 원본(U+5916) 1건만 남음. 다음 단계: 시사점·업무 연결 AI 생성 설계. 검증: unittest 261개 중 260개 통과, 1개 Skip
- D-041: 시사점·우리 업무와의 연결 AI 생성 구현 (src/saba/insights.py, 별도 호출·별도 저장 data/insights.db, 문장 번호 근거 필수, "AI 분석:" 표시, 부서 연결은 경영전략팀·기술개발연구소·보안사업팀만, STE본 카드는 "업무 범위 확인 중입니다."). openai_adapter 호출·사용량 기록 부분을 send_once() 로 분리해 재사용. build_views(insight_calls=0) 기본은 신규 호출 없음. Mock 검증만, 실제 호출은 다음 실행에서 별도 승인. 검증: unittest 268개 중 267개 통과, 1개 Skip
- D-042: 시사점·업무 연결 실제 생성 1회: 19건 모두 유효 (실패 0), 이번 비용 약 $0.006, 누적 호출 95건 약 $0.047, data/insights.db 19건. Preview·.eml 에 "AI 분석:" 시사점·업무 연결 표시. 품질 문제: 부서 연결이 19건 모두 보안사업팀 하나이고 문장이 비슷함 (경영전략팀·기술개발연구소 연결 0건). 추가 호출 없이 종료, 사용자 결정 대기. 검증: unittest 268개 중 267개 통과, 1개 Skip
- D-043: insights.py 지시문 보완 (회사 소개 치우침 제거, 부서별 판단 예시 DEPARTMENT_EXAMPLES, 기사 고유 대상 언급, 일반 문구 반복 금지) 후 19건 재생성 1회: 19건 모두 유효. 부서 연결 경영전략팀 7·기술개발연구소 4·보안사업팀 17 (이전 0·0·19), 연결 문장에 제품명·CVE·공격 방식 포함. 일부 연결은 부서 판단이 어색함 (예: 제품 취약점을 경영전략팀에 연결). 이번 비용 약 $0.007, 누적 호출 114건 약 $0.053, data/insights.db 38행 (이전 지시문 결과 19행은 hash 가 달라 사용 안 함). 검증: unittest 269개 중 268개 통과, 1개 Skip
- D-044: 사용자 화면 확인 의견에 따라 시사점·업무 연결·부서 카드의 "AI 분석:" 표시 문구 제거 (근거 필수 검증은 유지, 호출 없음). 부서 판단 예시는 유지 (사용자 기준 제공 시 교체). 다음 단계: 회사 메일 TEST 발송 준비. 검증: unittest 269개 중 268개 통과, 1개 Skip
- D-045: 회사 메일 TEST 발송 명령 구현 (src/saba/send_mail.py, python -m saba.send_mail). 한비로메일 SMTP 465 SSL/TLS, 환경 변수 SABA_SMTP_HOST·SABA_SMTP_USER·SABA_SMTP_PASSWORD (값 미기록), 보낸 사람·받는 사람 서명 주소 1개 고정 (Cc·Bcc 거부), 기본 드라이런, --send 일 때만 1회·재시도 없음, 오류는 종류만 표시. Mock 테스트 7개. 드라이런 확인만 했고 실제 접속·발송은 하지 않음 (별도 승인). 검증: unittest 276개 중 275개 통과, 1개 Skip
- D-046: 회사 메일 실제 TEST 발송 1회 (.eml --reuse-only 재생성 후, 프로젝트 .venv Python): 결과 "SMTP 오류: SMTPResponseException", 재시도 없음. 사용자 확인 결과 메일 도착하지 않음. 실패 단계와 응답 코드를 알 수 없어 send_mail.py 보완 (단계·응답 코드 숫자만 표시, 서버 응답 문장 미표시, 종료(QUIT) 응답만 비정상인 경우는 발송 완료와 경고로 구분, 인증 오류 우선 처리). 재발송 없음. 검증: unittest 278개 중 277개 통과, 1개 Skip
- D-047: 작은 텍스트 진단 메일 (output/smtp_diagnostic.eml, 337 bytes) 1회 발송: "발송 단계, SMTPResponseException, 응답 코드 250". smtplib 소스 확인 결과 with 종료 시 QUIT 이 221 대신 250 으로 응답해 발송 단계의 원래 오류를 덮어씀 (서버 응답 순서 어긋남 추정). 두 번의 발송 모두 원래 원인이 가려졌음. send_mail.py 보완: with 미사용, 원래 오류 우선 보고, QUIT 실패는 연결 close 후 경고로만 표시. 크기는 원인이 아님 (337 bytes 도 같은 단계 실패). 재발송 없음. 검증: unittest 280개 중 279개 통과, 1개 Skip
- D-048: 수정된 코드로 작은 진단 메일 1회 재발송: "발송 단계, SMTPSenderRefused, 응답 코드 503" (MAIL FROM 거부), 재시도 없음, 메일 미도착. 분석: smtplib login() 은 AUTH 응답 503 도 성공으로 처리하므로 실제로는 인증이 완료되지 않았을 가능성이 높음 (이전 QUIT 250 응답 어긋남도 같은 맥락). send_mail.py 보완: 발송 전 EHLO 실행, AUTH 응답 235 만 인증 성공 인정, 실패 시 EHLO·AUTH 응답 코드와 서버가 알린 인증 방식 이름만 보고. 재발송 없음. 검증: unittest 281개 중 280개 통과, 1개 Skip
- D-049: 사용자 확인 (SMTP 아이디는 메일 주소 @ 앞부분, 비밀번호는 웹메일과 같음). 이번 실행만 SABA_SMTP_USER 의 @ 앞부분을 아이디로 써서 인증 확인 진단 1회: AUTH 235 통과 (인증 성공) 했으나 다시 "발송 단계, SMTPSenderRefused, 응답 코드 503" (MAIL FROM 거부), 메일 미도착, 재시도 없음. 인증 성공 후에도 MAIL FROM 503 이고 이전 QUIT 250 응답까지 보면 서버 응답이 명령과 어긋났을 가능성. send_mail.py 보완: 실패 시 명령 이름과 응답 코드 순서만 표시 (trace_codes, 명령 인자·인증 데이터·응답 문장 미기록). 재발송 없음. 검증: unittest 282개 중 281개 통과, 1개 Skip
- D-050: 응답 순서 진단 1회 (실행 시에만 아이디 @ 앞부분): "EHLO 250 AUTH 334 (인증 데이터) -1 AUTH 535 AUTH 235 MAIL 503 RSET 250", 메일 미도착, 재시도 없음. 원인 확인: smtplib login() 자동 선택이 CRAM-MD5 부터 시도, 서버가 CRAM-MD5 응답에 비정상 응답(-1)을 보내 이후 응답이 한 칸씩 밀림 (PLAIN 성공 235 가 LOGIN 시도에 읽히고, 서버는 LOGIN 진행 중이라 MAIL FROM 503). 아이디·비밀번호는 맞음 (PLAIN 235). send_mail.py 수정: 자동 선택 대신 AUTH PLAIN 한 가지만 사용 (465 SSL/TLS 안이라 암호화 전달). 재발송 없음. 사용자가 SABA_SMTP_USER 를 @ 앞부분으로 바꾸기로 함. 검증: unittest 282개 중 281개 통과, 1개 Skip
- Source 이용 조건(재배포·요약 사용 범위)은 미확인. 기사 본문 수집은 하지 않으며 RSS 메타데이터와 Feed 제공 발췌만 저장
- 16단계: OpenAI API 실제 연결 및 TEST 호출 검증 (형식 기준 완료)
- 12단계 기록: Newsletter Template 및 Preview 완료 승인 (D-011). 실제 이메일 호환성·발송 검증 완료를 의미하지 않음
- 13~15단계: 선택적 AI 보강 계층 설계, Provider 독립 오프라인 어댑터와 Mock 검증 (`src/saba/ai_adapter.py`), Provider·Model·비용·데이터·TEST 범위 결정 (D-013~D-017)
- 16단계 구현: `src/saba/openai_adapter.py` (stdlib urllib, Responses API, gpt-4o-mini 고정, Structured Output strict, store=false, 재시도 없음), 사용량 기록 `data/openai_usage.json`, 월 $3 로컬 방어선, 변환 실패 진단 detail·quote_occurrences (기사 내용 미기록)
- 16단계 실제 호출: 가상 Fixture 기사 5건, 누적 10건 (D-017 5건, D-018 4건, D-019 1건), 비용 약 $0.0036 (코드 단가 기준). 보완 3회 후 5건 모두 AnalysisResult v1 변환 성공
- 16단계 검증: 2026-10-07 HEAD 753834e 기준 unittest 199개 중 198개 통과, 1개 Skip (실제 호출 테스트), 실패 0개
- 16단계 후속 품질 기준 (D-022): 근거 다양성 경고 (거절 없음, 사람 검토), 지시문 category 정의, importance 기사 사실 판단 규칙, 실제 호출 테스트 상한 환경변수 SABA_OPENAI_LIVE_MAX_CALLS
- 주입 대조 실험 (D-021): 006 원본 importance "높음", 주입 문장 제거본 "보통" (1회 비교). 주입 영향 가능성 있음. AI importance는 참고값이며 Newsletter 반영 전 사람이 확정
- 실제 호출 누적 12건 (D-017~D-019, D-021), 비용 약 $0.0048 (코드 단가 기준)
- 남은 품질 검토: 근거 의미 일치는 사람 검토, importance 지시문 강화 효과와 005 category 정의 효과는 실제 호출로 미검증. 형식 검증 통과는 분석 품질 승인을 의미하지 않음

### 완료/구현 확인
- Python 실행 골격
- 공통 Article Schema 및 JSON 검증
- SQLite 저장·조회
- Source 조사 및 수집 구조 설계
- CERT-EU Security Advisories RSS 수집 코드
- 다중 Source RSS 수집 (17단계, 승인 Source 5개)
- RSS 재수집 동일 원문 생략 및 변경 충돌 방지 구조
- Newsletter HTML Renderer·동적 Template과 SAMPLE Preview 구현 및 사용자 Preview 승인. 운영 발행 기능 완료를 의미하지 않음
- AI 분석 결과 Schema/검증 구조
- 합성 분석 결과의 별도 SQLite 저장·읽기 전용 조회 (`data/analysis.db`)
- 정규화 Analysis Input Snapshot 저장 및 Hash·출처·근거 위치 재검증
- 동일 분석 결과 생략 및 최초 저장 시각 유지
- 동일 입력의 다른 분석 결과 이력 보관 (기존 결과 불변)
- 분석 저장 전체 입력 Transaction/Rollback 및 기사 DB 읽기 전용 검증
- 분석 저장·조회 CLI: 합성 결과 3건 저장, 재입력 3건 생략, 다른 결과 1건 추가와 별도 프로세스 조회 확인
- 2026-10-07 검증: Python 3.12.14에서 unittest 전체 112개 통과. 임시 DB만 사용했고 실제 AI API는 호출하지 않음

### 현재 AI 상태
- 승인: Provider OpenAI (D-013), Model gpt-4o-mini (D-014), 월 최대 $3 (D-015), 전송 데이터 original_title + feed_excerpt만 (D-016), TEST·보완 호출 누적 10건 (D-017~D-019, 모두 소진)
- 실제 호출은 가상 Fixture 기사로만 수행했다. 실제 운영 기사 AI 분석, 분석 결과 DB 저장, Newsletter 반영은 미승인이다.
- 추가 실제 호출은 건별 사용자 승인이 필요하다. extracted_text 전송과 다른 모델 사용은 미승인이다.
- API Key는 환경변수 `OPENAI_API_KEY`로만 읽으며 코드·로그·사용량 기록에 남기지 않는다.
- Article 수집·정규화·저장은 AI와 독립적이다. AI는 선택적 보강 계층이며 AI 없이도 가능한 Core Pipeline 완성을 목표로 한다.
- 기존 Analysis Schema·검증·Storage·관련 테스트와 Fixture는 보존한다.

### 미구현/별도 승인 대상
- 실제 운영 기사 AI 분석 및 결과 저장·Newsletter 반영
- AI 분석 품질 기준 실제 효과 검증 (importance 주입 저항 반복 실험, category 정의 효과) 및 importance 사람 확정 절차 설계
- 추가 Source 확대 (순서: 공식 RSS 묶음 → 언론 묶음(중복 처리 설계 후) → 공식 데이터 API(CISA KEV, NVD), D-025)
- 필요한 Source의 Web Crawling
- 사건 단위 중복 통합
- 관련 부서 자동 분류
- 최종 뉴스레터 분석 필드 확정
- Newsletter 실제 이메일 호환성 검증 및 운영 발행 정책
- 회사 메일 연동 및 TEST/PRODUCTION 모드
- Scheduler
- 관리자 UI
- 서버/Cloud 배포
- 운영 ON/OFF 및 운영 로그 화면
- 최종 운영 DB 구조 및 DB 제품 선정
- 운영 로그 / 실행 이력 저장 구조
- 데이터·로그 보관 / Archive 정책
- DB Backup / Restore 정책

## 수집 구조 원칙
Source와 Newsletter Category를 분리한다.

Core Pipeline 목표: 승인 Source → 수집 → 공통 Article 정규화 → 저장 → 승인된 비AI 처리 → Newsletter 생성 → Mail 발송 → Scheduler

AI 분석·분류는 선택적 보강 경로다. Newsletter HTML 생성과 AI 없는 fallback은 구현됐고 Preview 사용자 승인을 받았다. 운영 기사 선별·Mail·Scheduler는 아직 구현되지 않았으며, AI 장애 격리도 현재는 설계 원칙이다. 원본에 없는 요약·중요도·부서·시사점 등을 임의 생성하지 않는다.

특정 Source를 특정 Newsletter Category에 1:1로 고정하지 않는다.
`SABA_NEWS_SOURCES.md`에 존재한다는 사실만으로 구현 또는 네트워크 접근이 승인된 것은 아니다.

## 운영 방향
최종 자동 실행은 사용자의 개인 PC가 아니라 24시간 동작 가능한 서버/Cloud 환경에서 수행한다.

향후 관리자 UI 목표:
- 시스템 상태 및 자동 실행 ON/OFF
- 발송 시간 변경
- TEST / PRODUCTION 모드
- 테스트 수신자 설정
- 수동 실행 및 테스트 메일
- Newsletter Preview
- 최근 실행 결과 및 로그

관리 UI 구현 방식과 배포 방식은 별도 설계·사용자 승인 후 확정한다.

## 단계 관리 원칙
1. 새 단계 시작 전 실제 Git 상태와 기존 테스트를 확인한다.
2. 완료된 기능을 단계 번호 때문에 다시 구현하지 않는다.
3. 설계 → 구현 → 실행 → 결과 확인 → 수정 → 사용자 확인 순으로 진행한다.
4. 각 단계는 `harness/` 아래의 모든 규칙 파일을 읽고 현재 작업에 관련된 범위에서 적용한다.
5. 필수 테스트 실패를 숨기거나 다음 단계로 넘어가지 않는다.
6. 단계 완료 후 실제 검증 결과에 맞는 문서 갱신안을 제시하고 사용자 승인 후 반영한다.
7. 다음 단계 프롬프트 작성 자체는 다음 단계 실행 승인이 아니다.
