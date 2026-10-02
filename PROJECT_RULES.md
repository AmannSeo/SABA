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

다음 파일은 사용자가 확정한
뉴스레터 디자인 기준 원본이다.

- `SAMPLE/Codex/layout_sample.html`
- `SAMPLE/Codex/style.css`

두 파일은 REFERENCE / BASELINE이다.

## DO NOT MODIFY

사용자의 명시적인 요청 또는 승인 없이
위 두 파일을 직접 수정하지 않는다.

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

`SAMPLE/Codex/layout_sample.html`
= 확정된 디자인 기준 원본

`SAMPLE/Codex/style.css`
= 확정된 Style 기준 원본

`templates/newsletter.html`
= Python 자동 생성용 Template

Template은 원본 디자인과 구조를 최대한 유지한다.


---

## 7. Newsletter Structure

현재 확정된 뉴스레터 순서:

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

다음 파일은 원본 보호 대상이다.

- `SAMPLE/Codex/layout_sample.html`
- `SAMPLE/Codex/style.css`
- `sign/sign.html`
- `sign/sign.css`
- `sign/sign_img.jpg`

사용자의 명시적인 요청 또는 승인 없이
직접 수정, 이동, 이름 변경, 삭제하지 않는다.

필요한 경우 별도의 작업 파일 또는 Template을 생성한다.