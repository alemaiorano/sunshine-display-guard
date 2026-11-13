import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_scan',ROOT/'tools/check_public.py')
scanner=importlib.util.module_from_spec(spec);spec.loader.exec_module(scanner)


class ScannerTests(unittest.TestCase):
    def test_credential_blob_is_rejected_even_with_innocent_name(self):
        value=b'-----BEGIN '+b'OPENSSH '+b'PRIVATE KEY-----'
        self.assertTrue(scanner.scan('notes.txt',value))
    def test_private_address_is_rejected_without_copying_real_profile(self):
        # Construct a synthetic non-documentation address, not a real machine.
        value='.'.join(map(str,[10,23,45,67])).encode()
        self.assertTrue(scanner.scan('notes.txt',value))
    def test_external_denylist_does_not_expose_matched_value(self):
        errors=scanner.scan('notes.txt',b'private-fixture-marker',deny=['private-fixture-marker'])
        self.assertTrue(errors);self.assertNotIn('private-fixture-marker',' '.join(errors))
    def test_local_config_filename_is_rejected_but_example_allowed(self):
        self.assertTrue(scanner.scan('config.json',b'{}'))
        self.assertFalse(scanner.scan('examples/config.json',b'{}'))
    def test_github_noreply_metadata_is_allowed(self):
        self.assertFalse(scanner.scan('metadata',b'12345+public-contributor@users.noreply.github.com'))
