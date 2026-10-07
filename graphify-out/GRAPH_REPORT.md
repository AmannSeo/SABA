# Graph Report - SABA  (2026-10-07)

## Corpus Check
- 71 files · ~201,400 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 16 file(s) not represented in the graph (top: .css 12, .xml 2, .example 1)

## Summary
- 702 nodes · 1565 edges · 33 communities (20 shown, 13 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 157 edges (avg confidence: 0.9)
- Token cost: 503,258 input · 0 output

## Community Hubs (Navigation)
- Test Imports & Stdlib
- Newsletter Renderer
- AI Adapter Core
- Analysis Input Model
- Mock Adapter Tests
- Project Rules & Decisions
- CLI & RSS Parsing
- Codex Layout Lineage
- Meeting Overview Pipeline
- MCP Connections
- Analysis Validation Tests
- MCP Best Practices
- Browser & Design Skills
- Claude Briefing Samples
- MCP Evaluation Harness
- Schema Tests
- Storage CLI Tests
- Analysis CLI Tests
- RSS HTTP Fetch
- Language Checker
- Eval Arg Parsing
- Base CLI Tests
- TBELL Vector Logo
- TBELL Logo v07
- TBELL Logo v09
- Source Collection Priority
- Signature Logo
- Future Admin UI
- D-017 Test Scope
- Package Root

## God Nodes (most connected - your core abstractions)
1. `AdapterTests` - 42 edges
2. `build_newsletter_html()` - 35 edges
3. `Article` - 33 edges
4. `NewsletterTests` - 30 edges
5. `build_article_view()` - 29 edges
6. `validate_articles()` - 29 edges
7. `save_analysis()` - 28 edges
8. `AnalysisStorageTests` - 28 edges
9. `save_articles()` - 27 edges
10. `OpenAIAdapterTests` - 25 edges

## Surprising Connections (you probably didn't know these)
- `Mock and Fixture Rules (no operational DB, no secrets in fixtures)` --semantically_similar_to--> `Secrets Policy (env vars, no .env commit)`  [INFERRED] [semantically similar]
  harness/TESTING_RULES.md → PROJECT_RULES.md
- `Collection-Classification Flow (collect, normalize+dedupe, AI classify, place, reselect)` --semantically_similar_to--> `SABA Core Pipeline (Source > Collect > Normalize > Store > Non-AI processing > Newsletter > Mail > Scheduler)`  [INFERRED] [semantically similar]
  SABA_NEWS_SOURCES.md → harness/AI_RULES.md
- `Newsletter Automation Template (templates/newsletter.html)` --conceptually_related_to--> `Company Email Signature HTML (sign.html)`  [AMBIGUOUS]
  templates/newsletter.html → sign/sign.html
- `main()` --uses--> `AnalysisResult`  [INFERRED]
  output/build_preview.py → src/saba/analysis.py
- `main()` --uses--> `SourceReference`  [INFERRED]
  output/build_preview.py → src/saba/schema.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **mcp-builder Reference Documentation Library** — _claude_skills_mcp_builder_skill_mcp_builder, _claude_skills_mcp_builder_reference_mcp_best_practices_mcp_best_practices, _claude_skills_mcp_builder_reference_node_mcp_server_node_mcp_server_guide, _claude_skills_mcp_builder_reference_python_mcp_server_python_mcp_server_guide, _claude_skills_mcp_builder_reference_evaluation_evaluation_guide [EXTRACTED 1.00]
- **Language-specific MCP tool registration and input validation** — _claude_skills_mcp_builder_reference_node_mcp_server_mcp_typescript_sdk, _claude_skills_mcp_builder_reference_node_mcp_server_zod_schemas, _claude_skills_mcp_builder_reference_python_mcp_server_fastmcp, _claude_skills_mcp_builder_reference_python_mcp_server_pydantic_v2_models, _claude_skills_mcp_builder_reference_mcp_best_practices_security_best_practices [INFERRED 0.85]
- **Anti-slop design guardrail flow** — _claude_skills_design_taste_frontend_skill_brief_inference, _claude_skills_design_taste_frontend_skill_three_dials, _claude_skills_design_taste_frontend_skill_ai_tells, _claude_skills_design_taste_frontend_skill_em_dash_ban, _claude_skills_design_taste_frontend_skill_final_pre_flight_check [INFERRED 0.85]
- **Approved OpenAI optional AI layer constraints (D-013..D-017)** — harness_rules_decisions_d_013_openai_provider, harness_rules_decisions_d_014_gpt_4o_mini, harness_rules_decisions_d_015_cost_limit, harness_rules_decisions_d_016_data_scope, harness_rules_decisions_d_017_first_test_call [EXTRACTED 1.00]
- **Newsletter template rendering into AI / non-AI previews** — templates_newsletter, templates_newsletter_placeholders, output_newsletter_preview_no_ai, output_newsletter_preview_with_ai, development_status_stage_12_newsletter_template_preview [INFERRED 0.85]
- **Prompt lifecycle governance (validation, decisions, next prompt, termination)** — harness_rules_prompt_validation, harness_rules_decisions, harness_rules_next_prompt_template, harness_rules_prompt_validation_termination_states [EXTRACTED 1.00]
- **Claude Sec & AI Briefing Sample Iterations v1-v4** — sample_claude_sec_ai_briefing_sample, sample_claude_sec_ai_briefing_sample_v2, sample_claude_sec_ai_briefing_sample_v3, sample_claude_sec_ai_briefing_sample_v4 [INFERRED 0.85]
- **Briefing Target Departments** — sample_claude_sec_ai_briefing_sample_dept_strategy, sample_claude_sec_ai_briefing_sample_dept_rnd, sample_claude_sec_ai_briefing_sample_dept_security_biz, sample_claude_sec_ai_briefing_sample_dept_ste [EXTRACTED 1.00]
- **Briefing Article Card Pattern** — sample_claude_sec_ai_briefing_sample_urgency_verification_badges, sample_claude_sec_ai_briefing_sample_implication_block, sample_claude_sec_ai_briefing_sample_selection_criteria, sample_claude_sec_ai_briefing_sample_deep_news_sections [INFERRED 0.85]
- **Security & AI Briefing newsletter layout iterations (sample, v2-v5)** — sample_codex_v02_layout_review_v2_page, sample_codex_v02_layout_sample_page, sample_codex_v03_layout_review_v3_page, sample_codex_v04_layout_review_v4_page, sample_codex_v05_layout_review_v5_page [INFERRED 0.85]
- **Briefing summary presentation variants** — sample_codex_v04_layout_review_v4_brief_view_switch, sample_codex_v04_layout_review_v4_brief_summary_view, sample_codex_v05_layout_review_v5_brief_compact_group [INFERRED 0.75]
- **Newsletter layout review iterations v6-v9 (v9 drops Today's Pick, approved)** — sample_codex_v06_layout_review_v6, sample_codex_v07_layout_review_v7, sample_codex_v08_layout_review_v8, sample_codex_v09_layout_review_v9 [INFERRED 0.95]
- **SABA pipeline stages from collection to newsletter** — saba_meeting_overview_2026_10_07_cert_eu_rss_collection, saba_meeting_overview_2026_10_07_article_normalization, saba_meeting_overview_2026_10_07_provider_independent_ai_adapter, saba_meeting_overview_2026_10_07_analysisresult_v1, saba_meeting_overview_2026_10_07_dynamic_newsletter_template [EXTRACTED 1.00]
- **v9 newsletter section structure** — sample_codex_v09_layout_review_v9_todays_briefing, sample_codex_v09_layout_review_v9_department_issues, sample_codex_v09_layout_review_v9_deep_news, sample_codex_v09_layout_review_v9_security_habit, sample_codex_v09_layout_review_v9_selection_criteria [EXTRACTED 1.00]

## Communities (33 total, 13 thin omitted)

### Community 0 - "Test Imports & Stdlib"
Cohesion: 0.07
Nodes (18): reconcile_articles(), AnalysisMetadata, Article, EvidenceReference, SourceReference, validate_articles(), check_structure(), get_article() (+10 more)

### Community 1 - "Newsletter Renderer"
Cohesion: 0.07
Nodes (21): main(), _analysis_is_ready(), article_section(), ArticleView, _build_anchor_map(), build_article_view(), build_newsletter_html(), _clean_excerpt() (+13 more)

### Community 2 - "AI Adapter Core"
Cohesion: 0.07
Nodes (19): AdapterError, AdapterOutcome, AnalysisRequest, convert_response(), AnalysisResult, build_body(), error_code(), http_transport() (+11 more)

### Community 3 - "Analysis Input Model"
Cohesion: 0.08
Nodes (18): canonical_json(), EvidenceSpan, FeedTextParser, input_payload(), InputSnapshot, json_hash(), normalize_text(), check_structure() (+10 more)

### Community 4 - "Mock Adapter Tests"
Cohesion: 0.08
Nodes (5): availability(), MockProviderError, prepare_request(), run_mock(), AdapterTests

### Community 5 - "Project Rules & Decisions"
Cohesion: 0.05
Nodes (34): SABA DEVELOPMENT STATUS, Synthetic Analysis Result Storage (data/analysis.db), Stage 12 - Newsletter Template and Preview (completed), Stage 13 - OpenAI Optional AI Enrichment Layer Design, SABA AI RULES v1.2, SABA Core Pipeline (Source > Collect > Normalize > Store > Non-AI processing > Newsletter > Mail > Scheduler), SABA DECISIONS log, D-003 Article Summary Policy (feed_excerpt only, no truncation summary) (+26 more)

### Community 6 - "CLI & RSS Parsing"
Cohesion: 0.10
Nodes (11): main(), read_articles(), read_json(), validate_file(), parse_feed(), publication_time(), RssError, select_articles() (+3 more)

### Community 7 - "Codex Layout Lineage"
Cohesion: 0.08
Nodes (33): 부서별 주요 이슈 (Department Issues) Section, Departments: 경영전략팀, 기술개발연구소, 보안사업팀, STE본부, Layout Review v2 (Security & AI Briefing), 보안 심층 뉴스 (Security Deep News) Section, Source Row List (source-title/name/date), 오늘의 브리핑 (Today's Briefing) Section, Today's Pick Section, 부서별 주요 이슈 (Department Issues) Section (+25 more)

### Community 8 - "Meeting Overview Pipeline"
Cohesion: 0.08
Nodes (26): SABA 프로젝트 진행 현황 (meeting overview 2026-10-07), AnalysisResult v1, Article normalization, stable ID, dedup/conflict handling, CERT-EU RSS collection (step 6), Dynamic Newsletter Template & Preview (step 12), Provider-independent AI Adapter with Mock verification (step 14), Remaining work (Notion, mail TEST, HTML email compat, Scheduler, Admin UI, source expansion), SABA pipeline (수집→정규화·중복→선택적 AI 분석→HTML Newsletter→회사 메일→매일 자동 실행) (+18 more)

### Community 9 - "MCP Connections"
Cohesion: 0.11
Nodes (5): create_connection(), MCPConnection, MCPConnectionHTTP, MCPConnectionSSE, MCPConnectionStdio

### Community 10 - "Analysis Validation Tests"
Cohesion: 0.12
Nodes (4): analysis_input(), AnalysisError, validate_analysis(), AnalysisTests

### Community 11 - "MCP Best Practices"
Cohesion: 0.14
Nodes (21): Apache License 2.0, MCP Server Evaluation Guide, Evaluation Runner (stdio/SSE/HTTP transports), 10 Read-only Complex Evaluation Questions (XML qa_pair), MCP Server Best Practices, Pagination (limit/offset, has_more), Response Formats (JSON vs Markdown), Security Best Practices (auth, input validation, DNS rebinding) (+13 more)

### Community 12 - "Browser & Design Skills"
Cohesion: 0.10
Nodes (17): agent-browser Skill, agent-browser CLI (Rust, CDP), Observability Dashboard (port 4848), agent-browser Specialized Skills (electron, slack, dogfood, agentcore, vercel-sandbox), Apple Liquid Glass Web Approximation, Block Library Contract, Dark Mode Protocol / Page Theme Lock, Brief to Design System Map (+9 more)

### Community 13 - "Claude Briefing Samples"
Cohesion: 0.23
Nodes (15): Sec & AI Briefing Sample v1 (Claude), Deep News Sections (국내 보안 / 해외 보안 / AI 동향), 기술개발연구소 (Tech R&D Institute), 보안사업팀 (Security Business Team), STE본부 (STE Division), 경영전략팀 (Management Strategy Team), Security & AI Briefing Newsletter, Sec & AI Briefing Sample v2 (Claude) (+7 more)

### Community 14 - "MCP Evaluation Harness"
Cohesion: 0.19
Nodes (5): agent_loop(), evaluate_single_task(), extract_xml_content(), parse_evaluation_file(), run_evaluation()

### Community 18 - "RSS HTTP Fetch"
Cohesion: 0.42
Nodes (3): fetch_feed(), NoRedirect, HttpTests

### Community 19 - "Language Checker"
Cohesion: 0.39
Nodes (3): check(), is_allowed(), main()

### Community 20 - "Eval Arg Parsing"
Cohesion: 0.33
Nodes (3): main(), parse_env_vars(), parse_headers()

### Community 26 - "TBELL Logo v07"
Cohesion: 0.67
Nodes (3): Red/White Stencil Brand Identity, TBELL Security (brand), TBELL Security Logo

### Community 27 - "TBELL Logo v09"
Cohesion: 0.67
Nodes (3): Red/White Brand Palette, TBELL Security (brand), TBELL Security Logo

## Ambiguous Edges - Review These
- `agent-browser Specialized Skills (electron, slack, dogfood, agentcore, vercel-sandbox)` → `tasteskill: Anti-Slop Frontend Skill`  [AMBIGUOUS]
  .claude/skills/design-taste-frontend/SKILL.md · relation: conceptually_related_to
- `Company Email Signature HTML (sign.html)` → `Newsletter Automation Template (templates/newsletter.html)`  [AMBIGUOUS]
  templates/newsletter.html · relation: conceptually_related_to

## Knowledge Gaps
- **61 isolated node(s):** `saba`, `Observability Dashboard (port 4848)`, `Brief to Design System Map`, `Redesign Protocol (Audit Before Touching)`, `Block Library Contract` (+56 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 195 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `agent-browser Specialized Skills (electron, slack, dogfood, agentcore, vercel-sandbox)` and `tasteskill: Anti-Slop Frontend Skill`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `Article` connect `Test Imports & Stdlib` to `Newsletter Renderer`, `AI Adapter Core`, `Analysis Input Model`, `Mock Adapter Tests`, `CLI & RSS Parsing`, `Analysis Validation Tests`, `Schema Tests`, `Storage CLI Tests`, `Department Validators`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `AdapterTests` (e.g. with `AdapterError` and `MockProviderError`) actually correct?**
  _`AdapterTests` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `saba`, `Observability Dashboard (port 4848)`, `Brief to Design System Map` to the rest of the system?**
  _61 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Test Imports & Stdlib` be split into smaller, more focused modules?**
  _Cohesion score 0.07437518819632641 - nodes in this community are weakly interconnected._
- **What is the exact relationship between `Company Email Signature HTML (sign.html)` and `Newsletter Automation Template (templates/newsletter.html)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `AdapterTests` connect `Mock Adapter Tests` to `Test Imports & Stdlib`, `Newsletter Renderer`, `AI Adapter Core`, `Analysis Validation Tests`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._