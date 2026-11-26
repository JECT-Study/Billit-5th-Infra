"""ject-domain의 이름 순서·env 파일 수정 함수를 임시 파일로 확인."""
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/ject-domain'
SOURCE = SCRIPT.read_text()
FUNCS = SOURCE[SOURCE.index('valid_name() {'):SOURCE.index('\nbackup() {')]
KEYS = "AUTH_URL_KEYS='POLICY_CONTENT_BASE_URL|TRIP_INVITATION_BASE_URL'\n"


def run(body):
    return subprocess.run(['bash', '-c', 'set -euo pipefail\n' + KEYS + FUNCS + '\n' + body],
                          capture_output=True, text=True, timeout=5)


class JectDomainTest(unittest.TestCase):
    def test_new_name_goes_first_and_old_names_stay(self):
        out = run('prepend_name billit.kr "jectbillit.duckdns.org 203-0-113-10.sslip.io"').stdout.strip()
        self.assertEqual(out, 'billit.kr jectbillit.duckdns.org 203-0-113-10.sslip.io')

    def test_same_name_is_not_duplicated(self):
        out = run('prepend_name billit.kr "jectbillit.duckdns.org billit.kr"').stdout.strip()
        self.assertEqual(out, 'billit.kr jectbillit.duckdns.org')

    def test_name_validation(self):
        for good in ('billit.kr', 'dev.billit.kr', 'dev.jectbillit.duckdns.org'):
            self.assertEqual(run(f'valid_name {good}').returncode, 0, good)
        for bad in ('Billit.kr', 'billit', 'billit.kr/x', 'a b.kr', '-x.kr', 'x.kr;rm', ''):
            self.assertNotEqual(run(f"valid_name '{bad}'").returncode, 0, bad)

    def test_env_files_change_only_host(self):
        with tempfile.TemporaryDirectory() as d:
            edge, auth, obs = (Path(d) / n for n in ('edge.env', 'auth.env', 'obs.env'))
            edge.write_text('PROD_DOMAIN="jectbillit.duckdns.org"\nDEV_UPSTREAM=10.0.0.1:8080\n')
            auth.write_text('JWT_SECRET=x\nPOLICY_CONTENT_BASE_URL=https://jectbillit.duckdns.org/terms\n'
                            'TRIP_INVITATION_BASE_URL=https://jectbillit.duckdns.org/invitations\n')
            obs.write_text('PROBE_PROD_URL=https://jectbillit.duckdns.org/readyz\n'
                           'PROBE_DEV_URL=https://dev.jectbillit.duckdns.org/readyz\n'
                           'PROBE_DEV_FE_URL=https://dev.jectbillit.duckdns.org/healthz\nPROBE_X_URL=\n')
            r = run(f'''
set_var {edge} PROD_DOMAIN '"billit.kr jectbillit.duckdns.org"'
set_var {edge} DEV_DOMAIN '"dev.billit.kr"'
set_url_host {auth} "$AUTH_URL_KEYS" billit.kr
set_url_host {obs} PROBE_PROD_URL billit.kr
set_url_host {obs} 'PROBE_DEV_URL|PROBE_DEV_FE_URL' dev.billit.kr
''')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(edge.read_text(), 'PROD_DOMAIN="billit.kr jectbillit.duckdns.org"\n'
                                               'DEV_UPSTREAM=10.0.0.1:8080\nDEV_DOMAIN="dev.billit.kr"\n')
            self.assertEqual(auth.read_text(), 'JWT_SECRET=x\nPOLICY_CONTENT_BASE_URL=https://billit.kr/terms\n'
                                               'TRIP_INVITATION_BASE_URL=https://billit.kr/invitations\n')
            self.assertEqual(obs.read_text(), 'PROBE_PROD_URL=https://billit.kr/readyz\n'
                                              'PROBE_DEV_URL=https://dev.billit.kr/readyz\n'
                                              'PROBE_DEV_FE_URL=https://dev.billit.kr/healthz\nPROBE_X_URL=\n')


if __name__ == '__main__':
    unittest.main()
