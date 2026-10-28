import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import oss_retention as r


def entry(version):
    return {'version': version, 'platforms': {'windows': {'url': r.BASE + 'releases/v' + version + '/package.zip'}}}


class RetentionTests(unittest.TestCase):
    def test_stable_occupies_one_of_five_slots(self):
        selected = r.select_releases([entry('1.2.' + str(i)) for i in [9, 8, 7, 6, 5]], entry('1.2.4'))
        self.assertEqual([x['version'] for x in selected], ['1.2.9', '1.2.8', '1.2.7', '1.2.6', '1.2.4'])

    def test_numeric_sort(self):
        self.assertEqual(r.select_releases([entry('1.2.9'), entry('1.2.10')], entry('1.2.9'))[0]['version'], '1.2.10')

    def test_boundaries(self):
        keys = ['releases/v1.2.0/a.zip', 'desktop-dashboard/releases/v1.2.0/a.zip',
                'releases/latest.json', 'releases/v1.2.9/a.zip', 'releases/vbad/a.zip',
                'releases/v1.2.0/../secret', 'releases-other/v1.2.0/a.zip']
        self.assertEqual(r.obsolete_objects(keys, {'1.2.9'}), [keys[0]])

    def test_invalid_catalog_fails_closed(self):
        for catalog in [[], [entry('../1')], [entry('1.2.9'), entry('1.2.9')]]:
            with self.assertRaises(ValueError):
                r.select_releases(catalog, entry('1.2.4'))

    def test_download_path_validation(self):
        for url in ['https://evil.example/releases/v1.2.9/x', r.BASE + 'desktop-dashboard/releases/v1.2.9/x',
                    r.BASE + 'releases/v1.2.9/%2e%2e/x', r.BASE + 'releases/v1.2.8/x']:
            with self.assertRaises(ValueError):
                r.url_key(url, '1.2.9')

    def run_fake(self, apply, deny=False, silently_ignore=False):
        catalog = [entry('1.2.9')]
        keys = {'releases/v1.2.9/package.zip', 'releases/v1.2.0/old.zip'}
        deleted = []
        class Bucket:
            def get_object(self, key):
                return io.BytesIO(json.dumps(catalog if key.endswith('releases.json') else catalog[0]).encode())
            def delete_object(self, key):
                if deny:
                    raise PermissionError('AccessDenied')
                deleted.append(key)
                if not silently_ignore:
                    keys.remove(key)
        with tempfile.TemporaryDirectory() as directory, patch.object(r, 'Path', return_value=Path(directory) / 'report.json'), patch.object(r, 'verify_downloads', return_value=1):
            r.enforce(Bucket(), lambda *a, **kw: [SimpleNamespace(key=k, size=100) for k in keys], apply)
        return deleted

    def test_dry_run_never_deletes(self):
        self.assertEqual(self.run_fake(False), [])

    def test_apply_deletes_only_obsolete(self):
        self.assertEqual(self.run_fake(True), ['releases/v1.2.0/old.zip'])

    def test_permission_failure_is_not_success(self):
        with self.assertRaises(PermissionError):
            self.run_fake(True, deny=True)

    def test_silent_failed_delete_is_detected(self):
        with self.assertRaisesRegex(ValueError, 'Deletion incomplete'):
            self.run_fake(True, silently_ignore=True)


if __name__ == '__main__':
    unittest.main()
