"""Release configuration contract; no credentials or network access."""
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]

class PublishingContract(unittest.TestCase):
    def test_only_published_releases_can_publish_separately_built_artifacts(self):
        path = ROOT / '.github/workflows/release.yml'
        self.assertTrue(path.is_file(), 'A maintained release workflow is required')
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow['on']['release']['types'], ['published'])
        self.assertIn('main', workflow['on']['push']['branches'])
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        jobs = workflow['jobs']
        self.assertEqual(jobs['publish']['needs'], 'build')
        self.assertEqual(jobs['publish']['environment']['name'], 'pypi')
        self.assertEqual(jobs['publish']['permissions'], {'contents': 'read'})
        self.assertIn("github.event_name == 'release'", jobs['publish']['if'])
        self.assertFalse(any('checkout' in s.get('uses','') for s in jobs['publish']['steps']))
        self.assertTrue(any('download-artifact@' in s.get('uses','') for s in jobs['publish']['steps']))
        self.assertTrue(any('gh-action-pypi-publish@' in s.get('uses','') for s in jobs['publish']['steps']))
        builds = '\n'.join(s.get('run','') for s in jobs['build']['steps'])
        self.assertIn('tools/test_project.py library', builds)
        self.assertIn('--library-root', builds)
        self.assertIn('twine check --strict', builds)
        self.assertIn('tomllib', builds)
        self.assertIn('RELEASE_TAG', builds)
        self.assertNotIn('secrets.', str(jobs['build']))
        publisher = next(s for s in jobs['publish']['steps'] if 'gh-action-pypi-publish@' in s.get('uses',''))
        self.assertEqual(publisher['with']['password'], '${{ secrets.PYPI_API_TOKEN }}')
        self.assertEqual(publisher['with']['attestations'], 'false')
        for job in jobs.values():
            for step in job['steps']:
                if 'uses' in step:
                    self.assertRegex(step['uses'], r'^[A-Za-z0-9_./-]+@[0-9a-f]{40}$')

if __name__ == '__main__':
    unittest.main()
