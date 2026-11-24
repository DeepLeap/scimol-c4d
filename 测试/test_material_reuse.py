"""Document-local SciMol material reuse policy, with C4D replaced by fakes."""

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Material:
    def __init__(self, document=None, graph_state=None):
        self.document = document
        self.graph_state = graph_state if graph_state is not None else ["original graph"]
        self.user_data = []
        self.values = {}
        self.next = None
        self.private = DataContainer()

    def GetDataInstance(self):
        return self.private

    def RemoveUserData(self, desc):
        self.user_data = [(key, data) for key, data in self.user_data if key != desc]
        self.values.pop(desc, None)

    def GetUserDataContainer(self):
        return self.user_data

    def AddUserData(self, container):
        desc = len(self.user_data)+1
        self.user_data.append((desc, container))
        return desc

    def __getitem__(self, desc):
        return self.values[desc]

    def __setitem__(self, desc, value):
        self.values[desc] = value

    def GetDocument(self):
        return self.document

    def GetNext(self):
        return self.next

    def Remove(self):
        self.document.materials.remove(self)
        self.document._link_materials()
        self.document = None


class DataContainer(dict):
    def __getitem__(self, key):
        return self.get(key)

    def SetString(self, key, value):
        self[key] = value


class Document:
    def __init__(self, materials=(), first_object=None):
        self.materials = list(materials)
        self.first_object = first_object
        for material in self.materials:
            material.document = self
        self.undo_calls = []
        self.undo_open = False
        self._link_materials()

    def _link_materials(self):
        for index, material in enumerate(self.materials):
            material.next = self.materials[index+1] if index+1 < len(self.materials) else None

    def GetFirstMaterial(self):
        return self.materials[0] if self.materials else None

    def GetFirstObject(self):
        return self.first_object

    def StartUndo(self):
        self.undo_open = True
        return True

    def EndUndo(self):
        self.undo_open = False

    def AddUndo(self, kind, target):
        self.undo_calls.append((kind, target))
        return True

    def InsertMaterial(self, material):
        self.materials.append(material)
        material.document = self
        self._link_materials()


class Root:
    def __init__(self, document=None, tags=()):
        self.document = document
        self.tags = list(tags)
        self.meta = None
        self.next = None

    def GetDown(self):
        return None

    def GetNext(self):
        return self.next

    def GetTags(self):
        return self.tags

    def GetDocument(self):
        return self.document


class DescID:
    def __init__(self, key, dtype):
        self.key = key
        self.level = types.SimpleNamespace(dtype=dtype)

    def GetDepth(self):
        return 1

    def __getitem__(self, index):
        assert index == 0
        return self.level


class Tag:
    def __init__(self, material, *, texture=True, other_material=None,
                 unreadable_link=False):
        self.texture = texture
        self.values = {100: material}
        if other_material is not None:
            self.values[101] = other_material
        self.unreadable_link = unreadable_link

    def CheckType(self, kind):
        return self.texture and kind == 200

    def __getitem__(self, key):
        if isinstance(key, DescID):
            if key.key == 110050 or (self.unreadable_link and key.key == 101):
                raise AttributeError("Parameter value not accessible (object unknown in Python)")
            key = key.key
        return self.values[key]

    def __setitem__(self, key, value):
        self.values[key] = value

    def GetDescription(self, flags):
        return [({}, DescID(110050, 1), None),
                *[({}, DescID(key, 2), None) for key in self.values]]


class MaterialReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c4d = types.ModuleType("c4d")
        cls.c4d.DESC_NAME = 1
        cls.c4d.DTYPE_STRING = 2
        cls.c4d.GetCustomDataTypeDefault = lambda dtype: {}
        cls.c4d.BaseObject = type("BaseObject", (), {})
        cls.c4d.documents = types.SimpleNamespace(BaseDocument=Document)
        cls.c4d.Ttexture = 200
        cls.c4d.TEXTURETAG_MATERIAL = 100
        cls.c4d.DESCFLAGS_DESC_NONE = 0
        cls.c4d.DTYPE_BASELISTLINK = 2
        cls.c4d.UNDOTYPE_CHANGE_SMALL = 301
        cls.c4d.UNDOTYPE_CHANGE = 300
        cls.c4d.UNDOTYPE_DELETEOBJ = 302
        cls.c4d.StopAllThreads = lambda: None
        cls.c4d.EventAdd = lambda: None
        cls.maxon = types.ModuleType("maxon")
        cls.maxon.Id = lambda value: value
        cls.stub = patch.dict(sys.modules, {"c4d": cls.c4d, "maxon": cls.maxon})
        cls.stub.start()
        cls.builder = importlib.import_module("scimol_c4d.c4d_builder")
        cls.snapshot = patch.object(cls.builder, "_material_graph_snapshot",
                                    side_effect=lambda mat: mat.graph_state)
        cls.snapshot.start()

    @classmethod
    def tearDownClass(cls):
        cls.snapshot.stop()
        cls.stub.stop()
        sys.modules.pop("scimol_c4d.c4d_builder", None)

    def make_managed(self, doc, key, color):
        mat = Material(doc)
        self.builder._set_material_uuid(mat)
        self.builder._set_material_spec(mat, key, color)
        return mat

    def test_internal_material_data_creates_no_visible_user_data(self):
        mat = self.make_managed(None, ("atom", "C"), [.18, .18, .18])
        self.assertEqual(mat.GetUserDataContainer(), [])
        self.assertIsNotNone(mat.GetDataInstance()[self.builder._PRIVATE_DATA_ID])
        self.assertEqual(self.builder._get_material_spec(mat)[0:2], ("atom", "C"))

    def test_legacy_fields_migrate_without_removing_user_fields(self):
        b = self.builder
        mat = Material()
        legacy_id = mat.AddUserData({self.c4d.DESC_NAME: b._MATERIAL_MARKER})
        mat[legacy_id] = "old-material-id"
        user_id = mat.AddUserData({self.c4d.DESC_NAME: "用户备注"})
        mat[user_id] = "保留"
        doc = Document([mat])
        doc.GetMaterials = lambda: doc.materials
        doc.GetObjects = lambda: []
        self.assertEqual(b.migrate_scene_user_data(doc), 1)
        self.assertEqual(b._material_uuid(mat), "old-material-id")
        self.assertEqual(mat.GetUserDataContainer(), [(user_id, {self.c4d.DESC_NAME: "用户备注"})])
        self.assertEqual(mat[user_id], "保留")
        self.assertEqual(b.migrate_scene_user_data(doc), 0)
        self.assertEqual(len(doc.undo_calls), 1)

    def test_private_data_collision_is_refused_before_migration(self):
        b = self.builder
        mat = Material()
        legacy_id = mat.AddUserData({self.c4d.DESC_NAME: b._MATERIAL_MARKER})
        mat[legacy_id] = "old-material-id"
        mat.private[b._PRIVATE_DATA_ID] = "foreign data"
        doc = Document([mat])
        doc.GetMaterials = lambda: doc.materials
        doc.GetObjects = lambda: []
        with self.assertRaises(ValueError): b.migrate_scene_user_data(doc)
        self.assertEqual(mat[legacy_id], "old-material-id")
        self.assertEqual(doc.undo_calls, [])

    def test_exact_role_key_and_color_reused_idempotently(self):
        atom = self.make_managed(None, ("atom", "C"), [0.18, 0.18, 0.18])
        bond = self.make_managed(None, ("bond", "C"), [0.18, 0.18, 0.18])
        doc = Document([atom, bond])
        wanted = {("atom", "C"): [0.18, 0.18, 0.18],
                  ("bond", "C"): [0.18, 0.18, 0.18]}
        self.assertEqual(self.builder._reusable_materials(doc, wanted),
                         {("atom", "C"): atom, ("bond", "C"): bond})
        self.assertEqual(self.builder._reusable_materials(doc, wanted),
                         {("atom", "C"): atom, ("bond", "C"): bond})
        self.assertEqual(self.builder._reusable_materials(
            doc, {("atom", "C"): [0.19, 0.18, 0.18]}), {})

    def test_foreign_or_manually_edited_material_not_reused(self):
        own = self.make_managed(None, ("atom", "O"), [0.85, 0.12, 0.10])
        foreign = Material()
        doc = Document([own, foreign])
        foreign.document = Document()
        wanted = {("atom", "O"): [0.85, 0.12, 0.10]}
        self.assertEqual(self.builder._reusable_materials(doc, wanted),
                         {("atom", "O"): own})
        own.graph_state = ["hand edited"]
        self.assertEqual(self.builder._reusable_materials(doc, wanted), {})
        self.assertEqual(self.builder._reusable_materials(
            Document(), wanted), {})

    def test_old_material_requires_unchanged_managed_root(self):
        old = Material()
        self.builder._set_material_uuid(old)
        root = Root()
        doc = Document([old], root)
        wanted = {("atom", "C"): [0.18, 0.18, 0.18]}
        with (patch.object(self.builder, "_get_meta", return_value={"signature": "saved",
                      "record": {}, "style": {}}),
              patch.object(self.builder, "_signature", return_value="saved"),
              patch.object(self.builder, "_material_specs", return_value=wanted),
              patch.object(self.builder, "_prototype_materials",
                           return_value={("atom", "C"): old})):
            self.assertEqual(self.builder._reusable_materials(doc, wanted),
                             {("atom", "C"): old})
        with (patch.object(self.builder, "_get_meta", return_value={"signature": "saved",
                      "record": {}, "style": {}}),
              patch.object(self.builder, "_signature", return_value="changed"),
              patch.object(self.builder, "_material_specs", return_value=wanted),
              patch.object(self.builder, "_prototype_materials",
                           return_value={("atom", "C"): old})):
            self.assertEqual(self.builder._reusable_materials(doc, wanted), {})

    def test_imported_duplicate_relinks_only_new_root_and_removes_unused_material(self):
        original = self.make_managed(None, ("atom", "C"), [0.18, 0.18, 0.18])
        duplicate = self.make_managed(None, ("atom", "C"), [0.18, 0.18, 0.18])
        doc = Document([original, duplicate])
        old_root = Root(doc, [Tag(original)])
        imported = Root(doc, [Tag(duplicate)])
        old_root.next = imported
        doc.first_object = old_root

        def signature(root):
            return tuple(id(tag.values[100]) for tag in root.tags)

        imported.meta = {"marker": "SciMol", "signature": signature(imported)}
        with (patch.object(self.builder, "_get_meta", side_effect=lambda root: root.meta),
              patch.object(self.builder, "_put_meta", side_effect=lambda root, meta: setattr(root, "meta", meta)),
              patch.object(self.builder, "_signature", side_effect=signature),
              patch.object(self.builder, "_walk", side_effect=lambda root: iter((root,)))):
            result = self.builder.deduplicate_imported_materials(doc, [imported], [duplicate])
        self.assertEqual(result, {"relinked": 1, "removed": 1})
        self.assertIs(imported.tags[0][100], original)
        self.assertIs(old_root.tags[0][100], original)
        self.assertEqual(doc.materials, [original])
        self.assertEqual(imported.meta["signature"], signature(imported))
        self.assertFalse(doc.undo_open)
        self.assertEqual([kind for kind, _target in doc.undo_calls], [301, 301, 302])

    def test_external_tag_reference_prevents_material_deletion(self):
        original = self.make_managed(None, ("bond", "C"), [0.18, 0.18, 0.18])
        duplicate = self.make_managed(None, ("bond", "C"), [0.18, 0.18, 0.18])
        doc = Document([original, duplicate])
        imported = Root(doc, [Tag(duplicate)])
        foreign = Root(doc, [Tag(None, texture=False, other_material=duplicate)])
        imported.next = foreign
        doc.first_object = imported

        def signature(root):
            return tuple(id(tag.values[100]) for tag in root.tags)

        imported.meta = {"signature": signature(imported)}
        with (patch.object(self.builder, "_get_meta", side_effect=lambda root: root.meta),
              patch.object(self.builder, "_put_meta", side_effect=lambda root, meta: setattr(root, "meta", meta)),
              patch.object(self.builder, "_signature", side_effect=signature),
              patch.object(self.builder, "_walk", side_effect=lambda root: iter((root,)))):
            result = self.builder.deduplicate_imported_materials(doc, [imported], [duplicate])
        self.assertEqual(result, {"relinked": 1, "removed": 0})
        self.assertIs(imported.tags[0][100], original)
        self.assertIs(foreign.tags[0][101], duplicate)
        self.assertEqual(doc.materials, [original, duplicate])

    def test_unreadable_actual_link_keeps_imported_material(self):
        original = self.make_managed(None, ("bond", "C"), [0.18, 0.18, 0.18])
        duplicate = self.make_managed(None, ("bond", "C"), [0.18, 0.18, 0.18])
        doc = Document([original, duplicate])
        imported = Root(doc, [Tag(duplicate)])
        foreign = Root(doc, [Tag(None, texture=False, other_material=duplicate,
                                 unreadable_link=True)])
        imported.next = foreign
        doc.first_object = imported

        def signature(root):
            return tuple(id(tag.values[100]) for tag in root.tags)

        imported.meta = {"signature": signature(imported)}
        with (patch.object(self.builder, "_get_meta", side_effect=lambda root: root.meta),
              patch.object(self.builder, "_put_meta", side_effect=lambda root, meta: setattr(root, "meta", meta)),
              patch.object(self.builder, "_signature", side_effect=signature),
              patch.object(self.builder, "_walk", side_effect=lambda root: iter((root,)))):
            result = self.builder.deduplicate_imported_materials(doc, [imported], [duplicate])
        self.assertEqual(result, {"relinked": 1, "removed": 0})
        self.assertIn(duplicate, doc.materials)

    def test_mismatched_or_edited_material_and_geometry_are_not_rewritten(self):
        original = self.make_managed(None, ("atom", "C"), [0.18, 0.18, 0.18])
        different_role = self.make_managed(None, ("bond", "C"), [0.18, 0.18, 0.18])
        doc = Document([original, different_role])
        imported = Root(doc, [Tag(different_role)])
        doc.first_object = imported

        def signature(root):
            return tuple(id(tag.values[100]) for tag in root.tags)

        imported.meta = {"signature": signature(imported)}
        with (patch.object(self.builder, "_get_meta", side_effect=lambda root: root.meta),
              patch.object(self.builder, "_put_meta", side_effect=lambda root, meta: setattr(root, "meta", meta)),
              patch.object(self.builder, "_signature", side_effect=signature),
              patch.object(self.builder, "_walk", side_effect=lambda root: iter((root,)))):
            self.assertEqual(self.builder.deduplicate_imported_materials(
                doc, [imported], [different_role]), {"relinked": 0, "removed": 0})
            self.assertIs(imported.tags[0][100], different_role)
            imported.meta["signature"] = ("manual edit",)
            with self.assertRaisesRegex(ValueError, "手工修改"):
                self.builder.deduplicate_imported_materials(doc, [imported], [different_role])
        self.assertEqual(doc.undo_calls, [])


if __name__ == "__main__":
    unittest.main()
