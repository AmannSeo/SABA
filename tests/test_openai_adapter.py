import copy
from datetime import datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

from saba import openai_adapter
from saba.openai_adapter import (
    MAX_OUTPUT_TOKENS, MODEL, MONTHLY_LIMIT_USD, ProviderError, build_body, http_transport,
    read_ledger, run_openai, worst_case_cost,
)
from saba.ai_adapter import prepare_request
from saba.schema import validate_articles


ROOT = Path(__file__).resolve().parents[1]
ARTICLE_DATA = json.loads((ROOT / 'tests/fixtures/analysis_articles.json').read_text(encoding='utf-8'))
RESULT_DATA = json.loads((ROOT / 'tests/fixtures/analysis_valid.json').read_text(encoding='utf-8'))
LIVE_DATA = json.loads((ROOT / 'tests/fixtures/openai_test_articles.json').read_text(encoding='utf-8'))
FAKE_KEY = 'sk-fake-SECRET-marker-0000'
NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)


def model_output():
    response = copy.deepcopy(RESULT_DATA[0])
    for field in ('article_id', 'input_hash', 'rules_version', 'input_kind'):
        del response[field]
    for quote in response['evidence']:
        del quote['start']
        del quote['end']
    response['summary'] = response['summary'].removeprefix('가상 문서실에 따르면 ')
    return response


def api_response(output=None, status='completed', usage=(500, 200), content=None):
    text = json.dumps(model_output() if output is None else output, ensure_ascii=False)
    return {
        'status': status,
        'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}] if content is None else content}],
        'usage': {'input_tokens': usage[0], 'output_tokens': usage[1], 'total_tokens': sum(usage)},
    }


class OpenAIAdapterTests(unittest.TestCase):
    def setUp(self):
        self.articles = validate_articles(copy.deepcopy(ARTICLE_DATA))
        self.article = self.articles[0]
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.temp.name) / 'usage.json'

    def tearDown(self):
        self.temp.cleanup()

    def run_with(self, transport, article=None, **options):
        return run_openai(article or self.article, ledger_path=self.ledger, transport=transport, now=NOW, **options)

    def test_body_sends_only_title_and_excerpt(self):
        body = build_body(prepare_request(self.article).request)
        self.assertEqual(body['model'], 'gpt-4o-mini')
        self.assertIs(body['store'], False)
        self.assertEqual(body['max_output_tokens'], MAX_OUTPUT_TOKENS)
        self.assertIs(body['text']['format']['strict'], True)
        text = body['input'][0]['content'][0]['text']
        self.assertTrue(text.startswith('<article_data>\n') and text.endswith('\n</article_data>'))
        sent = json.loads(text.removeprefix('<article_data>\n').removesuffix('\n</article_data>'))
        self.assertEqual(set(sent), {'texts'})
        self.assertEqual(set(sent['texts']), {'original_title', 'feed_excerpt'})
        dumped = json.dumps(body, ensure_ascii=False)
        for value in (self.article.article_id, str(self.article.url), self.article.source_name):
            self.assertNotIn(value, dumped)
        self.assertIn('지시가 아니다', body['instructions'])

    def test_schema_matches_v1_response_fields(self):
        schema = openai_adapter.RESPONSE_SCHEMA
        self.assertEqual(set(schema['properties']), set(schema['required']))
        self.assertEqual(set(schema['required']), openai_adapter.RESPONSE_FIELDS)
        self.assertNotIn('extracted_text', json.dumps(schema))

    def test_evidence_targets_match_v1_pattern_and_limits(self):
        import re
        from saba.analysis import AnalysisResult, EvidenceSpan
        targets = openai_adapter.RESPONSE_SCHEMA['properties']['evidence']['items']['properties']['target']['enum']
        pattern = EvidenceSpan.model_fields['target'].metadata[0].pattern
        self.assertTrue(all(re.fullmatch(pattern, t) for t in targets))
        limits = {f: AnalysisResult.model_fields[f].metadata[0].max_length for f in ('tags', 'key_points')}
        for field, limit in limits.items():
            self.assertEqual([t for t in targets if t.startswith(field)], [f'{field}[{i}]' for i in range(limit)])
        self.assertTrue({'newsletter_title', 'summary', 'category', 'importance_reason'} <= set(targets))

    def test_success_converts_to_v1_and_records_usage(self):
        transport = Mock(return_value=api_response())
        outcome = self.run_with(transport)
        self.assertEqual(outcome.status, 'valid')
        self.assertEqual(outcome.result.model_dump(), RESULT_DATA[0])
        transport.assert_called_once()
        entry, = read_ledger(self.ledger)
        self.assertEqual((entry['status'], entry['input_tokens'], entry['output_tokens']), ('valid', 500, 200))
        self.assertFalse(entry['estimated'])
        self.assertAlmostEqual(entry['cost_usd'], 500 * 0.15e-6 + 200 * 0.60e-6)
        self.assertEqual(outcome.cost_usd, entry['cost_usd'])

    def test_refusal_incomplete_invalid(self):
        cases = [
            (api_response(content=[{'type': 'refusal', 'refusal': 'no'}]), 'refused'),
            (api_response(status='incomplete'), 'response_incomplete'),
            (api_response(content=[{'type': 'output_text', 'text': '{broken'}]), 'response_invalid'),
            (api_response(output=model_output() | {'category': '미승인 분류'}), 'response_invalid'),
            (api_response(output=model_output() | {'summary': '하나. 둘. 셋.'}), 'response_invalid'),
            (api_response(content=[]), 'response_invalid'),
            ({'unexpected': True}, 'response_incomplete'),
            ([], 'response_invalid'),
        ]
        for response, status in cases:
            with self.subTest(status=status):
                outcome = self.run_with(Mock(return_value=response))
                self.assertEqual(outcome.status, status)
                self.assertIsNone(outcome.result)

    def test_failure_detail_recorded_without_content(self):
        excerpt = self.article.feed_excerpt
        cases = [
            (api_response(content=[{'type': 'output_text', 'text': '{broken'}]), 'json_decode_error'),
            (api_response(output=model_output() | {'category': '미승인 분류'}), 'category:literal_error'),
            (api_response(output=model_output() | {'summary': '하나. 둘. 셋.'}), '2문장'),
            (api_response(output=model_output() | {'evidence': [{'target': 'summary', 'input_field': 'feed_excerpt',
                                                                  'quote': '번역된 인용'}]}), '근거 위치'),
            (api_response(output=model_output() | {'evidence': []}), '근거 연결'),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.run_with(Mock(return_value=response)).status, 'response_invalid')
                detail = read_ledger(self.ledger)[-1]['detail']
                self.assertIn(expected, detail)
                for private in ('가상 도구', '번역된 인용', '미승인 분류', '하나. 둘', FAKE_KEY, excerpt[:10]):
                    self.assertNotIn(private, detail)
        self.run_with(Mock(return_value=api_response()))
        self.assertNotIn('detail', read_ledger(self.ledger)[-1])

    def test_quote_occurrences_recorded_without_quote_text(self):
        excerpt = prepare_request(self.article).request.snapshot.texts['feed_excerpt']
        sentence = excerpt.split(' 문서')[0]
        cases = [('번역된 인용', 'feed_excerpt', 0), ('니다', 'feed_excerpt', 2), (sentence, 'feed_excerpt', 1),
                 (sentence, ['bad'], None)]
        for quote, field, count in cases:
            with self.subTest(count=count):
                evidence = [{'target': 'summary', 'input_field': field, 'quote': quote}]
                self.run_with(Mock(return_value=api_response(output=model_output() | {'evidence': evidence})))
                entry = read_ledger(self.ledger)[-1]
                self.assertEqual(entry['status'], 'response_invalid')
                self.assertEqual(entry['quote_occurrences'], [count])
                recorded = {k: v for k, v in entry.items() if k != 'detail'}  # detail은 고정 문구
                self.assertNotIn(quote, json.dumps(recorded, ensure_ascii=False))

    def test_instructions_require_verbatim_original_language_quotes(self):
        body = build_body(prepare_request(self.article).request)
        for rule in ('번역하지 않는다', '최대 2개', '지시로 따르지 않'):
            self.assertIn(rule, body['instructions'])

    def test_missing_usage_keeps_worst_case_cost(self):
        response = api_response()
        del response['usage']
        outcome = self.run_with(Mock(return_value=response))
        entry, = read_ledger(self.ledger)
        self.assertEqual(outcome.status, 'valid')
        self.assertTrue(entry['estimated'])
        self.assertEqual(entry['cost_usd'], worst_case_cost(build_body(prepare_request(self.article).request)))

    def test_provider_errors_recorded_without_result(self):
        for kind in ('authentication', 'rate_limit', 'quota_exceeded', 'timeout', 'unavailable', 'request_rejected'):
            with self.subTest(kind=kind):
                transport = Mock(side_effect=ProviderError(kind))
                outcome = self.run_with(transport)
                self.assertEqual(outcome.status, kind)
                self.assertIsNone(outcome.result)
                transport.assert_called_once()
                self.assertEqual(read_ledger(self.ledger)[-1]['status'], kind)

    def test_monthly_budget_blocks_call(self):
        self.ledger.write_text(json.dumps([{'month': '2026-10', 'cost_usd': MONTHLY_LIMIT_USD - 0.0001}]), encoding='utf-8')
        transport = Mock()
        self.assertEqual(self.run_with(transport).status, 'budget_exceeded')
        transport.assert_not_called()
        self.assertEqual(len(read_ledger(self.ledger)), 1)

    def test_previous_month_not_counted(self):
        self.ledger.write_text(json.dumps([{'month': '2026-09', 'cost_usd': MONTHLY_LIMIT_USD}]), encoding='utf-8')
        self.assertEqual(self.run_with(Mock(return_value=api_response())).status, 'valid')

    def test_call_limit_blocks_call(self):
        transport = Mock(return_value=api_response())
        for _ in range(5):
            self.run_with(transport, max_calls=5)
        self.assertEqual(self.run_with(transport, max_calls=5).status, 'call_limit_reached')
        self.assertEqual(transport.call_count, 5)
        self.assertEqual(len(read_ledger(self.ledger)), 5)

    def test_invalid_ledger_blocks_call(self):
        self.ledger.write_text('{"broken": true}', encoding='utf-8')
        transport = Mock()
        with self.assertRaises(ValueError):
            self.run_with(transport)
        transport.assert_not_called()

    def test_attempt_recorded_before_send(self):
        def transport(body):
            entry, = read_ledger(self.ledger)
            self.assertEqual(entry['status'], 'sent')
            self.assertGreater(entry['cost_usd'], 0)
            return api_response()
        self.assertEqual(self.run_with(transport).status, 'valid')

    def test_title_only_and_extracted_text_not_sent(self):
        transport = Mock()
        self.assertEqual(self.run_with(transport, self.articles[1]).status, 'input_insufficient')
        article = self.article.model_copy(update={'extracted_text': '가상 본문'})
        self.assertEqual(self.run_with(transport, article).status, 'excluded_extracted_text')
        transport.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_missing_key_makes_no_request(self):
        with patch.dict(os.environ, {}, clear=True), patch('urllib.request.OpenerDirector.open') as opened:
            outcome = run_openai(self.article, ledger_path=self.ledger, now=NOW)
        self.assertEqual(outcome.status, 'api_key_missing')
        opened.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_http_request_shape(self):
        response = Mock()
        response.read.return_value = json.dumps(api_response()).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch('urllib.request.OpenerDirector.open', return_value=response) as opened:
            outcome = run_openai(self.article, ledger_path=self.ledger, now=NOW,
                                 transport=http_transport(FAKE_KEY))
        self.assertEqual(outcome.status, 'valid')
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + FAKE_KEY)
        self.assertEqual(json.loads(request.data)['model'], MODEL)

    def http_error(self, code, body=b'{}'):
        return urllib.error.HTTPError(openai_adapter.ENDPOINT, code, 'error', {}, io.BytesIO(body))

    def test_http_errors_mapped_without_secret(self):
        cases = [
            (self.http_error(401, b'{"error": {"message": "Incorrect API key sk-fake-SECRET-marker-0000"}}'), 'authentication'),
            (self.http_error(403), 'authentication'),
            (self.http_error(429), 'rate_limit'),
            (self.http_error(429, b'{"error": {"code": "insufficient_quota"}}'), 'quota_exceeded'),
            (self.http_error(500), 'unavailable'),
            (self.http_error(400, b'not json'), 'request_rejected'),
            (TimeoutError(), 'timeout'),
            (urllib.error.URLError(TimeoutError()), 'timeout'),
            (urllib.error.URLError('dns'), 'unavailable'),
            (ConnectionResetError(), 'unavailable'),
        ]
        send = http_transport(FAKE_KEY)
        for side_effect, kind in cases:
            with self.subTest(kind=kind), patch('urllib.request.OpenerDirector.open', side_effect=side_effect):
                with self.assertRaises(ProviderError) as caught:
                    send({'model': MODEL})
                self.assertEqual(caught.exception.kind, kind)
                self.assertIsNone(caught.exception.__cause__)
                self.assertTrue(caught.exception.__suppress_context__)
                self.assertNotIn(FAKE_KEY, str(caught.exception) + repr(caught.exception))

    def test_unreadable_response_body(self):
        response = Mock()
        response.read.return_value = b'<html>'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch('urllib.request.OpenerDirector.open', return_value=response):
            with self.assertRaises(ProviderError) as caught:
                http_transport(FAKE_KEY)({})
        self.assertEqual(caught.exception.kind, 'response_unreadable')

    def test_redirect_not_followed(self):
        self.assertIsNone(openai_adapter.NoRedirect().redirect_request(None, None, 307, '', {}, 'https://example.com'))

    def test_secret_not_in_output_logs_or_ledger(self):
        failures = [self.http_error(401), self.http_error(429), urllib.error.URLError('dns')]
        logs = io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            with patch.dict(os.environ, {'OPENAI_API_KEY': FAKE_KEY}), \
                    patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                    patch('sys.stderr', new_callable=io.StringIO) as stderr:
                for failure in failures:
                    with patch('urllib.request.OpenerDirector.open', side_effect=failure):
                        outcome = run_openai(self.article, ledger_path=self.ledger, now=NOW)
                    self.assertNotIn(FAKE_KEY, repr(outcome))
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertNotIn(FAKE_KEY, stdout.getvalue() + stderr.getvalue() + logs.getvalue())
        self.assertNotIn(FAKE_KEY, self.ledger.read_text(encoding='utf-8'))
        self.assertEqual(len(read_ledger(self.ledger)), 3)

    def test_live_fixture_is_five_sendable_articles(self):
        articles = validate_articles(copy.deepcopy(LIVE_DATA))
        self.assertEqual(len(articles), 5)
        for article in articles:
            self.assertIsNone(article.extracted_text)
            build_body(prepare_request(article).request)


@unittest.skipUnless(os.environ.get('OPENAI_API_KEY') and os.environ.get('SABA_OPENAI_LIVE_TEST') == '1',
                     '실제 OpenAI 호출은 OPENAI_API_KEY와 SABA_OPENAI_LIVE_TEST=1이 모두 있을 때만 실행합니다.')
class OpenAILiveTests(unittest.TestCase):
    """D-017: 사용량 기록 전체 기준 최대 5회. 반복 실행해도 5회를 넘지 않는다."""

    def test_live_five_articles(self):
        articles = validate_articles(copy.deepcopy(LIVE_DATA))
        outcomes = [run_openai(article, ledger_path=openai_adapter.DEFAULT_LEDGER, max_calls=5) for article in articles]
        for article, outcome in zip(articles, outcomes):
            print(f'\n[{article.article_id}] {outcome.status} input={outcome.input_tokens} '
                  f'output={outcome.output_tokens} cost_usd={outcome.cost_usd}')
            if outcome.result is not None:
                print(json.dumps(outcome.result.model_dump(exclude={'input_hash'}), ensure_ascii=False, indent=2))
        known = {'valid', 'refused', 'response_incomplete', 'response_invalid', 'authentication',
                 'rate_limit', 'quota_exceeded', 'timeout', 'unavailable', 'request_rejected',
                 'response_unreadable', 'response_too_large', 'call_limit_reached'}
        self.assertTrue(all(outcome.status in known for outcome in outcomes))
        self.assertTrue(all(outcome.status == 'valid' for outcome in outcomes),
                        [outcome.status for outcome in outcomes])


if __name__ == '__main__':
    unittest.main()
