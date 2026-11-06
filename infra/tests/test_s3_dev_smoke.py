import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

SPEC = importlib.util.spec_from_file_location('smoke', Path(__file__).with_name('s3-dev-smoke.py'))
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)
DATA = {'access_key': 'synthetic', 'secret_key': 'synthetic-only', 'region': 'ap-chuncheon-1',
        'endpoint': 'https://synthetic.compat.objectstorage.ap-chuncheon-1.oraclecloud.com'}


class S3DevSmokeTests(unittest.TestCase):
    def test_credentials_require_private_file_and_oci_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'credentials.json'
            path.write_text(json.dumps(DATA)); path.chmod(0o600)
            self.assertEqual(S.credentials(path), DATA)
            path.chmod(0o644)
            with self.assertRaises(ValueError): S.credentials(path)
            path.chmod(0o600)
            path.write_text(json.dumps({**DATA, 'endpoint': 'https://example.org'}))
            with self.assertRaises(ValueError): S.credentials(path)

    def test_presigned_url_has_short_lifetime_and_no_secret(self):
        url = S.presign(DATA, 'PUT', S.BUCKET, 'safe key.txt')
        self.assertNotIn(DATA['secret_key'], url)
        parsed = urllib.parse.urlsplit(url)
        self.assertEqual(parsed.path, '/ject-dev-uploads/safe%20key.txt')
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query['X-Amz-Expires'], ['60'])
        self.assertEqual(len(query['X-Amz-Signature'][0]), 64)
        self.assertNotEqual(url, S.presign(DATA, 'GET', S.BUCKET, 'safe key.txt'))

    def test_cleanup_occurs_when_hash_verification_fails(self):
        responses = [(200,b'', ''), (200,b'wrong', ''), (204,b'', ''), (404,b'', 'NoSuchKey')]
        with patch.object(S, 'request', side_effect=responses) as request:
            with self.assertRaisesRegex(RuntimeError, 'hash'): S.run(DATA)
        self.assertEqual([c.args[1] for c in request.call_args_list], ['PUT','GET','DELETE','GET'])
        self.assertTrue(all('/ject-dev-uploads/' in c.args[0] for c in request.call_args_list))

    def test_only_one_development_object_is_written_and_deleted(self):
        payload = b'JECT development S3 synthetic validation\n'
        responses = [(200,b'', ''), (200,payload,''), (200,b'',''), (403,b'','AccessDenied'),
                     (404,b'',''), (403,b'','AccessDenied'),
                     (403,b'','AccessDenied'), (204,b'',''), (404,b'','NoSuchKey')]
        with patch.object(S,'request', side_effect=responses) as request:
            result=S.run(DATA)
        self.assertTrue(result['signed_delete_and_missing'])
        self.assertTrue(result['signed_head'])
        self.assertEqual(result['expired_signed_get_denied']['status'], 403)
        mutations=[c for c in request.call_args_list if c.args[1] in ('PUT','DELETE')]
        self.assertEqual(len(mutations),2)
        self.assertTrue(all('/ject-dev-uploads/infra-validation/' in c.args[0] for c in mutations))

    def test_expired_url_success_or_signature_error_is_not_accepted(self):
        payload = b'JECT development S3 synthetic validation\n'
        for status, code in ((200, ''), (403, 'SignatureDoesNotMatch')):
            with self.subTest(status=status, code=code):
                responses = [(200,b'',''), (200,payload,''), (200,b'',''),
                             (status,b'',code), (204,b'',''), (404,b'','NoSuchKey')]
                with patch.object(S, 'request', side_effect=responses) as request:
                    with self.assertRaisesRegex(RuntimeError, 'expired'): S.run(DATA)
                self.assertEqual([c.args[1] for c in request.call_args_list][-2:], ['DELETE', 'GET'])

    def test_head_failure_cleans_the_synthetic_object(self):
        responses = [(200,b'',''), (200,b'JECT development S3 synthetic validation\n',''),
                     (403,b'','AccessDenied'), (204,b'',''), (404,b'','NoSuchKey')]
        with patch.object(S, 'request', side_effect=responses) as request:
            with self.assertRaisesRegex(RuntimeError, 'HEAD'): S.run(DATA)
        self.assertEqual([c.args[1] for c in request.call_args_list][-2:], ['DELETE', 'GET'])

    def test_put_connection_loss_still_cleans_own_key(self):
        with patch.object(S, 'request', side_effect=[OSError('connection lost'),
                         (204,b'',''), (404,b'','NoSuchKey')]) as request:
            with self.assertRaises(OSError): S.run(DATA)
        self.assertEqual([c.args[1] for c in request.call_args_list], ['PUT','DELETE','GET'])
