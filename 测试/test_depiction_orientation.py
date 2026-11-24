"""Straight 2D ring diagrams without changes to source geometry or cache hits."""
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rdkit import Chem
from rdkit.Chem import rdDepictor
from scimol_c4d import chemistry_worker as worker, resolve_cache
from scimol_c4d.records import DEPICTION_VERSION, record_integrity


class DepictionOrientationTests(unittest.TestCase):
    def test_six_membered_ring_is_horizontal_and_all_distances_are_preserved(self):
        for smiles in ('OC(C)c1ccccc1C', 'Cn1c(=O)c2c(ncn2C)n(C)c1=O'):
            with self.subTest(smiles=smiles):
                mol = Chem.MolFromSmiles(smiles)
                rdDepictor.Compute2DCoords(mol)
                conf = mol.GetConformer()
                before = [tuple(conf.GetAtomPosition(i)) for i in range(mol.GetNumAtoms())]
                worker._straighten_depiction(mol)
                after = [tuple(conf.GetAtomPosition(i)) for i in range(mol.GetNumAtoms())]
                ring = next(ring for ring in mol.GetRingInfo().AtomRings() if len(ring)==6)
                errors = [abs(after[a][1]-after[ring[(i+1)%6]][1])
                          for i,a in enumerate(ring)]
                self.assertLess(min(errors), 1e-10)
                for a in range(len(before)):
                    for b in range(len(before)):
                        self.assertAlmostEqual(math.dist(before[a],before[b]),
                                               math.dist(after[a],after[b]), places=10)

    def test_preview_upgrades_image_and_hotspots_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory).resolve()
            record = worker._from_smiles('OC(C)c1ccccc1C', '示例', {}, cache)
            record.pop('depiction_version')
            identity = record_integrity(record)
            source_block = record['molblock']
            result = worker._generate_preview(record, cache)
            self.assertEqual(result['depiction_version'],DEPICTION_VERSION)
            self.assertEqual(result['molblock'],source_block)
            self.assertEqual(record_integrity(result),identity)
            mol = Chem.MolFromMolBlock(source_block)
            ring = next(ring for ring in mol.GetRingInfo().AtomRings() if len(ring)==6)
            positions = result['thumbnail_atom_positions']
            self.assertEqual(set(positions), {str(a['id']) for a in record['atoms'] if a['element']!='H'})
            self.assertLess(min(abs(positions[str(a)][1]-positions[str(ring[(i+1)%6])][1])
                                for i,a in enumerate(ring)),1e-8)
            for field in ('thumbnail','transparent_thumbnail','transparent_dark_thumbnail'):
                self.assertTrue(Path(result[field]).is_file())

    def test_old_search_cache_redraws_locally_without_resolving_again(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory).resolve()
            request = {'action':'resolve','kind':'smiles','text':'OCc1ccccc1','cache_dir':str(cache)}
            old = worker.handle(request)['records']
            old[0].pop('depiction_version')
            resolve_cache.save(cache,'smiles',request['text'],old)
            with patch.object(worker,'_resolve',side_effect=AssertionError('Network/resolve repeated')):
                result = worker.handle(request)['records']
            self.assertEqual(result[0]['depiction_version'],DEPICTION_VERSION)
            self.assertEqual(record_integrity(result[0]),record_integrity(old[0]))
            with patch.object(worker,'_generate_preview',side_effect=AssertionError('Redrawn again')):
                self.assertEqual(worker.handle(request)['records'],result)


if __name__ == '__main__':
    unittest.main()
