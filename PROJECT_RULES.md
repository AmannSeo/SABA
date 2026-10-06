# SABA Project Rules

## 1. Project

SABA = Security & AI Briefing Automation

국내외 보안·AI 관련 정보를 자동 수집하고,
AI 분석을 거쳐 HTML 뉴스레터를 생성한 후
회사 메일로 정기 발송하는 시스템이다.


---

## 2. Development Rules

전체 시스템을 한 번에 구현하지 않는다.

작업은 다음 순서로 진행한다.

설계
→ 구현
→ 실행
→ 확인
→ 수정
→ 사용자 승인
→ 다음 단계

사용자의 승인 없이 다음 단계로 넘어가지 않는다.

확정되지 않은 요구사항을 임의로 결정하지 않는다.

기존 파일의 위치와 이름을
사용자 승인 없이 변경하지 않는다.


---

## 3. Current Project Structure

현재 프로젝트 구조:

SABA/
├─ SAMPLE/
│  ├─ Claude/
│  └─ Codex/
│     ├─ layout_sample.html
│     └─ style.css
└─ sign/
   ├─ sign_img.jpg
   ├─ sign.css
   └─ sign.html

SAMPLE/Claude 폴더의 역할은 현재 임의로 정의하지 않는다.

### Versioned Design Folders

뉴스레터 디자인 버전은 `SAMPLE/Codex/v숫자/` 폴더로 관리한다.
예: `v01/`, `v09/`, `v10/`.

사용자가 현재 지정한 디자인은 `SAMPLE/Codex/v09/`의 레이아웃 샘플이다.
새 버전이 추가되면 아래 최신 버전 선택 규칙을 적용한다.
위 구조 표는 기존 파일 구조이며, 실제 버전 폴더와 파일은 작업 시작 시 확인한다.


---

## 4. Technology

Backend / Automation:

Python

MVP에서는 별도의 Web Frontend를 만들지 않는다.

뉴스 수집 우선순위:

1. RSS
2. Official API
3. Web Crawling

Web Crawling은 RSS/API로 필요한 데이터를 얻기 어려운 경우에 검토한다.


---

# 5. PROTECTED - Newsletter Design

### Latest Design Baseline

매 작업 시작 시 `SAMPLE/Codex/`의 바로 아래에 있는 버전 폴더를 확인한다.
폴더명이 `^v[0-9]+# SABA Project Rules

## 1. Project

SABA = Security & AI Briefing Automation

국내외 보안·AI 관련 정보를 자동 수집하고,
AI 분석을 거쳐 HTML 뉴스레터를 생성한 후
회사 메일로 정기 발송하는 시스템이다.


---

## 2. Development Rules

전체 시스템을 한 번에 구현하지 않는다.

작업은 다음 순서로 진행한다.

설계
→ 구현
→ 실행
→ 확인
→ 수정
→ 사용자 승인
→ 다음 단계

사용자의 승인 없이 다음 단계로 넘어가지 않는다.

확정되지 않은 요구사항을 임의로 결정하지 않는다.

기존 파일의 위치와 이름을
사용자 승인 없이 변경하지 않는다.


---

## 3. Current Project Structure

현재 프로젝트 구조:

SABA/
├─ SAMPLE/
│  ├─ Claude/
│  └─ Codex/
│     ├─ layout_sample.html
│     └─ style.css
└─ sign/
   ├─ sign_img.jpg
   ├─ sign.css
   └─ sign.html

SAMPLE/Claude 폴더의 역할은 현재 임의로 정의하지 않는다.

### Versioned Design Folders

뉴스레터 디자인 버전은 `SAMPLE/Codex/v숫자/` 폴더로 관리한다.
예: `v01/`, `v09/`, `v10/`.

사용자가 현재 지정한 디자인은 `SAMPLE/Codex/v09/`의 레이아웃 샘플이다.
새 버전이 추가되면 아래 최신 버전 선택 규칙을 적용한다.
위 구조 표는 기존 파일 구조이며, 실제 버전 폴더와 파일은 작업 시작 시 확인한다.


---

## 4. Technology

Backend / Automation:

Python

MVP에서는 별도의 Web Frontend를 만들지 않는다.

뉴스 수집 우선순위:

1. RSS
2. Official API
3. Web Crawling

Web Crawling은 RSS/API로 필요한 데이터를 얻기 어려운 경우에 검토한다.


---

# 5. PROTECTED - Newsletter Design

 형식인 폴더만 대상으로 하며,
`v` 뒤의 값을 정수로 비교하여 가장 높은 버전을 선택한다.

- 문자열 정렬이나 수정 시각으로 최신 버전을 판단하지 않는다.
- 예: `v10`은 `v09`보다 높고, `v100`은 `v99`보다 높다.
- 현재 사용자 지정 기준은 `v09`이며, 이후 더 높은 버전이 있으면 해당 폴더를 기준으로 한다.
- 같은 숫자를 뜻하는 폴더가 여러 개 있으면(예: `v9`, `v09`) 임의로 선택하지 않고 사용자에게 확인한다.

선택한 폴더의 실제 레이아웃 HTML과 그 HTML이 참조하는 CSS·이미지·기타 자산을
확인한 뒤 REFERENCE / BASELINE으로 사용한다.
파일명은 실제 파일을 확인하며 임의로 추측하지 않는다.
다른 버전의 HTML/CSS/자산을 섞어 사용하지 않는다.

선택한 버전과 참조 파일 경로를 작업 결과에 명시한다.
버전 폴더가 없거나, 최고 버전의 필수 파일이 누락되거나,
여러 레이아웃 중 기준 파일이 불명확하면 해당 디자인에 의존하는 작업을 멈추고 확인을 요청한다.
구버전 또는 루트의 샘플로 임의 대체하지 않는다.

새 버전이 추가되면 다음 작업 시작 시 다시 확인하여 최고 버전을 기준으로 진행한다.
기존 자동화 Template이 있다면 차이를 검토하고 별도 Template에 필요한 변경을 반영한다.
원본 파일을 수정하거나 자동으로 메일을 발송·배포하는 근거로 사용하지 않는다.

기존 루트 샘플은 과거 기준 원본으로 보존한다.

- `SAMPLE/Codex/layout_sample.html`
- `SAMPLE/Codex/style.css`

모든 버전 폴더의 디자인 원본도 보호 대상이다.

## DO NOT MODIFY

사용자의 명시적인 요청 또는 승인 없이
기존 루트 샘플과 모든 버전 폴더의 디자인 원본 및 자산을 직접 수정하지 않는다.

다음 내용을 임의로 변경하지 않는다.

- Layout
- Section Order
- Colors
- Typography
- Font Size
- Spacing
- Cards
- Border
- Background
- Header
- Footer
- Text
- Information Hierarchy
- Newsletter Structure

코드 정리, 리팩터링, 디자인 개선,
자동화 구현, 반응형 개선,
이메일 호환성 개선 등의 이유로도
원본을 직접 수정하지 않는다.


---

## 6. Automation Template

동적 데이터 삽입을 위한 HTML이 필요한 경우
원본을 수정하지 않고 별도 Template을 생성한다.

예:

templates/
└─ newsletter.html

역할:

`SAMPLE/Codex/`의 최고 숫자 버전 폴더에 있는 레이아웃 HTML
= 현재 디자인 기준 원본

같은 버전의 HTML이 참조하는 CSS 및 자산
= 현재 Style / Asset 기준 원본

`templates/newsletter.html`
= Python 자동 생성용 Template

Template은 선택한 최신 버전 원본의 디자인과 구조를 최대한 유지한다.
Template 작업 결과에는 기준 버전과 참조 파일 경로를 기록한다.


---

## 7. Newsletter Structure

다음은 기존 뉴스레터 구조다.
최고 버전 디자인의 표시 문구·섹션 순서·구조와 다르면 최신 디자인을 시각적 기준으로 적용한다.
다만 기능 요구사항·원본 서명 보호·보안·단계별 승인 규칙과 충돌하는 내용은 임의로 변경하지 않고 사용자에게 확인한다.

기존 뉴스레터 순서:

1. Header
2. 인사말
3. 오늘의 브리핑
4. 부서별 주요 이슈
5. Security News 상세
6. AI & Tech 상세
7. 정보 수집 기준 / 주요 출처
8. 회사 메일 서명

Today's Pick은 사용하지 않는다.

기본 정보 흐름:

전체 동향
→ 부서별 관련 이슈
→ 상세 뉴스


---

# 8. PROTECTED - Company Email Signature

다음 파일은 실제 회사 메일 서명의 원본 세트다.

- `sign/sign.html`
- `sign/sign.css`
- `sign/sign_img.jpg`

위 3개 파일은 SOURCE OF TRUTH이다.

## DO NOT MODIFY

사용자의 명시적인 요청 또는 승인 없이
위 파일을 직접 수정하지 않는다.

다음 내용을 임의로 변경하지 않는다.

- 이름
- 직급
- 영문명
- 부서
- Mobile
- E-mail
- 홈페이지
- 회사 주소
- Logo
- Confidentiality Notice
- 서명의 기본적인 시각 구조

`sign/sign_img.jpg`를 다른 이미지로 임의 교체하지 않는다.

새로운 서명을 임의로 디자인하지 않는다.


---

## 9. Email Signature Template

이메일 클라이언트 호환성 때문에 변환이 필요한 경우
원본을 수정하지 않는다.

필요하면 별도 파일을 생성한다.

예:

templates/
└─ email_signature.html

원본:

`sign/sign.html`
`sign/sign.css`
`sign/sign_img.jpg`

발송용:

`templates/email_signature.html`

발송용 버전에서도 원본의 정보와
시각적 구조를 최대한 동일하게 유지한다.


---

## 10. Department Classification

현재 부서:

- 경영전략팀
- 기술개발연구소
- 보안사업팀
- STE본

STE본의 정확한 업무 범위는 아직 확정되지 않았다.

AI 또는 개발자가 STE본의 역할을 임의로 추론하여
뉴스 분류 규칙을 생성하지 않는다.

필요한 경우 사용자에게 확인한다.


---

## 11. Secrets

다음 정보를 Source Code에 직접 작성하지 않는다.

- AI API Key
- Notion API Key
- Mail Password
- SMTP Credentials
- OAuth Client Secret
- 기타 회사 인증정보

Secret은 환경변수 또는 적절한 Secret 관리 방법을 사용한다.

`.env`는 Git에 Commit하지 않는다.

`.env.example`에는 실제 Secret 값을 작성하지 않는다.


---

# 12. Protected Original Files

다음 파일과 모든 버전 폴더의 원본은 보호 대상이다.

- `SAMPLE/Codex/v숫자/` 내부의 레이아웃 HTML, CSS, 이미지 및 기타 디자인 자산

- `SAMPLE/Codex/layout_sample.html`
- `SAMPLE/Codex/style.css`
- `sign/sign.html`
- `sign/sign.css`
- `sign/sign_img.jpg`

사용자의 명시적인 요청 또는 승인 없이
직접 수정, 이동, 이름 변경, 삭제하지 않는다.

필요한 경우 별도의 작업 파일 또는 Template을 생성한다.