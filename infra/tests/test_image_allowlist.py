from pathlib import Path
import os
import subprocess
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/ject-deploy'

class ImageAllowlistTests(unittest.TestCase):
    def allowed(self, service, image, fe='ghcr.io/team/ject-fe'):
        text=SCRIPT.read_text()
        fn=text[text.index('image_allowed() {'):text.index('\ncompose() {')]
        env={**os.environ,'ALLOWED_IMAGE_PREFIX':'ghcr.io/old/ject-',
             'ALLOWED_FE_IMAGE_REPOSITORY':fe,'TEST_SERVICE':service,'TEST_IMAGE':image}
        return subprocess.run(['bash','-c',fn+'\nimage_allowed "$TEST_SERVICE" "$TEST_IMAGE"'],env=env).returncode==0

    def test_fe_exact_repository_does_not_widen_backend_allowlist(self):
        digest='@sha256:'+'a'*64
        self.assertTrue(self.allowed('fe','ghcr.io/team/ject-fe'+digest))
        self.assertTrue(self.allowed('fe','ghcr.io/team/ject-fe:verified'+digest))
        self.assertFalse(self.allowed('fe','ghcr.io/team/ject-fe-other'+digest))
        self.assertFalse(self.allowed('fe','ghcr.io/old/ject-fe'+digest))
        self.assertTrue(self.allowed('be','ghcr.io/old/ject-be'+digest))
        self.assertFalse(self.allowed('be','ghcr.io/team/ject-fe'+digest))

    def test_digest_and_configuration_validation(self):
        for value in ['ghcr.io/team/ject-fe:latest','ghcr.io/team/ject-fe@sha256:bad']:
            self.assertFalse(self.allowed('fe',value))
        self.assertFalse(self.allowed('fe','ghcr.io/team/ject-fe@sha256:'+'a'*64,fe='ghcr.io/'))
        self.assertTrue(self.allowed('fe','ghcr.io/old/ject-fe@sha256:'+'a'*64,fe=''))
