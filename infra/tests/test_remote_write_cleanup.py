import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('redis_rw_e2e', Path(__file__).with_name('redis-remote-write-e2e.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CleanupTests(unittest.TestCase):
    def run_case(self, container_rc=0, container_names='', network_rc=0, network_names='bridge\nhost\nnone\n'):
        def fake(*args, **kwargs):
            rc, out = 0, ''
            if args[:2] == ('container', 'ls'):
                rc, out = container_rc, container_names
            elif args[:2] == ('network', 'ls'):
                rc, out = network_rc, network_names
            return subprocess.CompletedProcess(args, rc, out, '')
        with patch.object(module, 'docker', side_effect=fake) as call:
            module.clean_owned(['synthetic-owned'], 'synthetic-network')
            self.assertFalse(any('prune' in c.args for c in call.call_args_list))

    def test_absence_is_proven_by_successful_listings(self):
        self.run_case(container_names='unrelated-container\n')

    def test_listing_errors_fail_closed(self):
        for kwargs in ({'container_rc': 42}, {'network_rc': 42}):
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                self.run_case(**kwargs)

    def test_owned_resources_remaining_fail(self):
        for kwargs in ({'container_names': 'synthetic-owned\n'}, {'network_names': 'synthetic-network\n'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                self.run_case(**kwargs)
