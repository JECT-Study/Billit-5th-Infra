#!/usr/bin/env python3
"""저부하 합성 거절시험: 임시 설정의 heap 한도만2MiB로 낮춘다. 운영값 아님."""
import importlib.util
from pathlib import Path
import tempfile

spec = importlib.util.spec_from_file_location('sanitize_memory', Path(__file__).with_name('otel-sanitize-e2e.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def main():
    text=fixture.RUNTIME.replace('import copy,', 'import urllib.error, copy,')
    start=text.index(' with urllib.request.urlopen(req,timeout=10) as response:')
    end=text.index("if sys.argv[1]=='server':",start)
    text=text[:start]+''' time.sleep(2) # limiter의1초관측주기 경과; 부하를 만들지 않음
 try:
  urllib.request.urlopen(req,timeout=10)
 except urllib.error.HTTPError as error:
  assert error.code==503, 'expected retriable memory refusal'
 else: raise RuntimeError('low memory limit did not refuse input')
 time.sleep(.5)
 assert not OUT.exists(), 'refused span reached exporter'
 print('PASS temporary2MiB limit: HTTP503; no export')
'''+text[end:]
    fixture.RUNTIME=text
    original=fixture.CONFIG.read_text()
    assert original.count('limit = "128MiB"')==1
    with tempfile.TemporaryDirectory(prefix='billit-otel-lowlimit-') as directory:
        config=Path(directory)/'lowlimit.alloy'
        config.write_text(original.replace('limit = "128MiB"','limit = "2MiB"').replace('spike_limit = "32MiB"','spike_limit = "1MiB"'))
        fixture.CONFIG=config
        fixture.main()

if __name__=='__main__':main()
