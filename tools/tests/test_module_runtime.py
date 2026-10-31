import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('module_runtime', Path(__file__).resolve().parents[1] / 'module_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class ModuleRuntimeTests(unittest.TestCase):
    def test_distinct_temp_and_no_inherited_import_injection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tools/environments').mkdir(parents=True)
            (root / 'tools/environments/modules.json').write_text(json.dumps({
                'a': {'directory': '甲'}, 'b': {'directory': '乙'}}), encoding='utf-8')
            with patch.dict(os.environ, {'PYTHONPATH': 'foreign', 'PYTHONHOME': 'foreign'}):
                _, a, _, ea = runtime.module_environment('a', root)
                _, b, _, eb = runtime.module_environment('b', root)
            self.assertNotEqual(ea['TEMP'], eb['TEMP'])
            self.assertNotIn('PYTHONPATH', ea)
            self.assertNotIn('PYTHONHOME', ea)
            self.assertEqual(ea['PYTHONNOUSERSITE'], '1')
            (a / 'run.py').write_text('pass')
            (b / 'run.py').write_text('pass')
            self.assertEqual(runtime.validate_script(root, a, {}, '甲/run.py'), a / 'run.py')
            with self.assertRaises(ValueError):
                runtime.validate_script(root, a, {}, '乙/run.py')
            with self.assertRaises(ValueError):
                runtime.validate_script(root, a, {}, '../outside.py')
            (a / '.venv/Scripts').mkdir(parents=True)
            (a / '.venv/Scripts/python.exe').write_bytes(b'')
            self.assertEqual(runtime.module_environment('a', root)[2], a / '.venv/Scripts/python.exe')


if __name__ == '__main__':
    unittest.main()
