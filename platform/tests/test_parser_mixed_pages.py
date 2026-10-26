import asyncio
from types import SimpleNamespace
import httpx
from talent_platform.worker import Worker


def test_native_cover_cannot_hide_a_scanned_resume_page(monkeypatch, tmp_path):
    import pypdf
    monkeypatch.setattr(pypdf, 'PdfReader', lambda path: SimpleNamespace(pages=[
        SimpleNamespace(extract_text=lambda: '合成简历封面' * 80), SimpleNamespace(extract_text=lambda: '')]))
    calls = []
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, **kwargs):
            calls.append(url)
            return httpx.Response(200, json={'text': '封面及扫描页完整文字'}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'AsyncClient', Client)
    path = tmp_path / 'synthetic-mixed.pdf'
    path.write_bytes(b'synthetic parser input')
    worker = Worker(SimpleNamespace(parser_url='http://mineru:8001', internal_service_key='test-key'), stores=object())
    result = asyncio.run(worker.parse(str(path), path.name))
    assert result == '封面及扫描页完整文字' and calls == ['http://mineru:8001/parse']
