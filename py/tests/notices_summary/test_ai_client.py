from __future__ import annotations

import httpx
import pytest
import respx

from skkuverse_crawler.notices_summary.ai_client import AiClient

BASE_URL = "http://test-ai:4000"
ENDPOINT = f"{BASE_URL}/api/notices/summarize"

SAMPLE_RESPONSE = {
    "oneLiner": "4/30까지 등록금 납부",
    "summary": "등록금 납부 안내입니다.",
    "type": "action_required",
    "periods": [
        {
            "label": None,
            "startDate": None,
            "startTime": None,
            "endDate": "2026-04-30",
            "endTime": None,
        }
    ],
    "locations": [],
    "details": {
        "target": None,
        "action": "등록금 납부",
        "host": None,
        "impact": None,
    },
    "model": "openai/gpt-4.1-mini",
}


class TestAiClientSummarize:
    @respx.mock
    async def test_success(self):
        respx.post(ENDPOINT).respond(json=SAMPLE_RESPONSE)
        client = AiClient(BASE_URL)
        try:
            result = await client.summarize("제목", "학사", "본문 텍스트")
            assert result["oneLiner"] == "4/30까지 등록금 납부"
            assert result["type"] == "action_required"
        finally:
            await client.close()

    @respx.mock
    async def test_sends_correct_payload(self):
        route = respx.post(ENDPOINT).respond(json=SAMPLE_RESPONSE)
        client = AiClient(BASE_URL)
        try:
            await client.summarize("제목", "카테고리", "본문")
            payload = route.calls[0].request.content
            import json
            body = json.loads(payload)
            assert body == {"title": "제목", "category": "카테고리", "cleanText": "본문"}
        finally:
            await client.close()

    @respx.mock
    async def test_retries_on_500(self):
        respx.post(ENDPOINT).side_effect = [
            httpx.Response(500),
            httpx.Response(200, json=SAMPLE_RESPONSE),
        ]
        client = AiClient(BASE_URL)
        try:
            result = await client.summarize("제목", "", "본문")
            assert result["oneLiner"] == "4/30까지 등록금 납부"
        finally:
            await client.close()

    @respx.mock
    async def test_raises_on_4xx(self):
        respx.post(ENDPOINT).respond(status_code=422)
        client = AiClient(BASE_URL)
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.summarize("제목", "", "본문")
        finally:
            await client.close()

    @respx.mock
    async def test_raises_after_all_retries_exhausted(self):
        respx.post(ENDPOINT).side_effect = [
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),
        ]
        client = AiClient(BASE_URL)
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.summarize("제목", "", "본문")
        finally:
            await client.close()
