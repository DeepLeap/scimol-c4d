"""Transparent 2D diagrams are sidecar assets, independent of scene geometry."""

import io
from pathlib import Path
import tempfile
import unittest
import uuid

from PIL import Image

from scimol_c4d import chemistry_worker as worker


class BackgroundPreviewTests(unittest.TestCase):
    def test_transparent_light_and_dark_ink_share_identical_hotspots(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            record = worker._from_smiles('OCc1ccccc1', '苄醇',
                                         {'kind': 'test'}, cache)
            source_positions = record['thumbnail_atom_positions']
            source_atoms = record['atoms']
            for field in ('transparent_thumbnail', 'transparent_dark_thumbnail'):
                image = Image.open(record[field])
                self.assertEqual(image.mode, 'RGBA')
                self.assertEqual(image.getpixel((0, 0))[3], 0)
                self.assertGreater(image.getbbox()[2], 0)
            dark = Image.open(record['transparent_thumbnail']).convert('RGBA')
            light = Image.open(record['transparent_dark_thumbnail']).convert('RGBA')
            self.assertEqual(dark.getchannel('A').tobytes(),
                             light.getchannel('A').tobytes())
            self.assertNotEqual(dark.tobytes(), light.tobytes())
            result = worker.handle({'action': 'previews', 'records': [record],
                                    'cache_dir': str(cache)})
            refreshed = result['records'][0]
            self.assertEqual(refreshed['thumbnail_atom_positions'], source_positions)
            self.assertEqual(refreshed['atoms'], source_atoms)
            self.assertEqual(refreshed['record_integrity'], record['record_integrity'])
            self.assertEqual(refreshed['transparent_thumbnail'], record['transparent_thumbnail'])

    def test_batch_limit_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(worker.ChemistryError):
                worker.handle({'action': 'previews', 'records': [{}] * 25,
                               'cache_dir': str(Path(directory))})

    def test_3d_generation_preserves_saved_configuration_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            original = worker._from_smiles('CO', '甲醇', {'kind': 'test'}, cache)
            identity = str(uuid.uuid4())
            original['configuration_id'] = identity
            original['list_source'] = '收藏'
            generated = worker._generate(original, cache)
            self.assertTrue(generated['coordinates_ready'])
            self.assertEqual(generated['configuration_id'], identity)
            self.assertEqual(generated['list_source'], '收藏')
            self.assertEqual(generated['structure_key'], original['structure_key'])
            self.assertEqual(generated['record_integrity'],
                             worker.record_integrity(generated))
            original['configuration_id'] = 42
            with self.assertRaises(worker.ChemistryError):
                worker._generate(original, cache)


if __name__ == '__main__':
    unittest.main()
