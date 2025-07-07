import os
import sys
import unittest
from unittest.mock import Mock, patch
import json
import yaml
import base64
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from noetl.keyval import KeyVal, KeyValBuilder

class TestKeyVal(unittest.TestCase):
    def setUp(self):
        self.test_data = {
            'name': 'test',
            'version': '1.0.0',
            'config': {
                'database': {
                    'host': 'localhost',
                    'port': 5432
                },
                'api': {
                    'timeout': 30,
                    'retries': 3
                }
            },
            'items': ['item1', 'item2', 'item3']
        }
        self.keyval = KeyVal(self.test_data)

    def test_keyval_initialization(self):
        kv = KeyVal()
        self.assertIsInstance(kv, dict)
        self.assertIsInstance(kv, KeyVal)

        kv_with_data = KeyVal(self.test_data)
        self.assertEqual(kv_with_data['name'], 'test')

    def test_builder_pattern(self):
        builder = KeyVal.builder()
        self.assertIsInstance(builder, KeyValBuilder)

    def test_info_property(self):
        kv = KeyVal()
        self.assertIsNone(kv.info)

        test_info = {'type': 'test', 'description': 'test keyval'}
        kv.info = test_info
        self.assertEqual(kv.info, test_info)

    def test_get_keys_root_level(self):
        keys = self.keyval.get_keys()
        expected_keys = ['name', 'version', 'config', 'items']
        self.assertEqual(sorted(keys), sorted(expected_keys))

    def test_get_keys_nested_path(self):
        keys = self.keyval.get_keys('config')
        expected_keys = ['config.database', 'config.api']
        self.assertEqual(sorted(keys), sorted(expected_keys))

    def test_get_keys_deeper_nested_path(self):
        keys = self.keyval.get_keys('config.database')
        expected_keys = ['config.database.host', 'config.database.port']
        self.assertEqual(sorted(keys), sorted(expected_keys))

    def test_get_keys_invalid_path(self):
        keys = self.keyval.get_keys('nonexistent')
        self.assertEqual(keys, [])

    def test_get_value_simple_key(self):
        value = self.keyval.get_value('name')
        self.assertEqual(value, 'test')

    def test_get_value_nested_key(self):
        value = self.keyval.get_value('config.database.host')
        self.assertEqual(value, 'localhost')

    def test_get_value_with_default(self):
        value = self.keyval.get_value('nonexistent', default='default_value')
        self.assertEqual(value, 'default_value')

    def test_get_value_no_path(self):
        value = self.keyval.get_value()
        self.assertEqual(value, self.test_data)

    def test_get_value_with_exclude(self):
        value = self.keyval.get_value(exclude=['version'])
        self.assertNotIn('version', value)
        self.assertIn('name', value)

    def test_set_value(self):
        kv = KeyVal()
        kv.set_value("a.b.c", 10)
        self.assertEqual(kv.get_value("a.b.c"), 10)

        with self.assertRaises(ValueError):
            kv.set_value("", 10)

        with self.assertRaises(ValueError):
            kv.set_value(None, 10)

    def test_delete_value(self):
        kv = KeyVal({"a": {"b": {"c": 10}}})
        kv.delete_value("a.b.c")
        self.assertIsNone(kv.get_value("a.b.c"))

    def test_delete_keys(self):
        kv = KeyVal({"a": 1, "b": 2, "c": 3})
        kv.delete_keys(["a", "c"])
        self.assertEqual(kv, {"b": 2})

    def test_retain_keys(self):
        kv = KeyVal({"a": 1, "b": 2, "c": 3})
        kv.retain_keys(["a", "c"])
        self.assertEqual(sorted(kv.keys()), ["a", "c"])

    def test_add_method(self):
        kv = KeyVal()
        result = kv.add("test.key", "value")
        self.assertIs(result, kv)
        self.assertEqual(kv.get_value("test.key"), "value")

    def test_to_json(self):
        kv = KeyVal({"a": 1, "b": 2})
        json_repr = kv.to_json()
        self.assertIsInstance(json_repr, bytes)
        self.assertEqual(json.loads(json_repr.decode('utf-8')), {"a": 1, "b": 2})

    def test_as_json(self):
        kv = KeyVal({'a': 1, 'b': 2})
        self.assertEqual(kv.as_json(path='a'), '1')
        self.assertEqual(kv.as_json(path='b'), '2')
        self.assertEqual(kv.as_json(indent=2), '{\n  "a": 1,\n  "b": 2\n}')

        with self.assertRaises(ValueError):
            kv.as_json(path='nonexistent')

    def test_get_keyval(self):
        kv = KeyVal({"nested": {"key": "value"}})
        nested_kv = kv.get_keyval("nested")
        self.assertIsInstance(nested_kv, KeyVal)
        self.assertEqual(nested_kv["key"], "value")

    def test_encode_decode(self):
        kv = KeyVal({"a": 1, "b": 2})
        encoded = kv.encode()
        self.assertIsInstance(encoded, bytes)

        decoded = KeyVal.decode(encoded)
        self.assertEqual(decoded, {"a": 1, "b": 2})

    def test_encode_with_keys(self):
        kv = KeyVal({"a": 1, "b": 2, "c": 3})
        encoded = kv.encode(keys=["a", "c"])
        decoded = KeyVal.decode(encoded)
        self.assertEqual(decoded, {"a": 1, "c": 3})

    def test_str_to_base64(self):
        result = KeyVal.str_to_base64("test")
        expected = base64.b64encode("test".encode()).decode()
        self.assertEqual(result, expected)

    def test_base64_to_str(self):
        encoded = base64.b64encode("test".encode()).decode()
        result = KeyVal.base64_to_str(encoded)
        self.assertEqual(result, "test")

    def test_base64_to_yaml(self):
        data = {"key": "value"}
        yaml_str = yaml.safe_dump(data)
        encoded = base64.b64encode(yaml_str.encode()).decode()
        result = KeyVal.base64_to_yaml(encoded)
        self.assertEqual(result, data)

    def test_yaml_dump(self):
        data = {"key": "value"}
        result = KeyVal.yaml_dump(data)
        self.assertIsInstance(result, str)
        self.assertEqual(yaml.safe_load(result), data)

    def test_base64_value(self):
        kv = KeyVal({"workflow_base64": "test"})
        result = kv.base64_value("workflow_base64")
        expected = base64.b64encode("test".encode()).decode()
        self.assertEqual(result, expected)

        with self.assertRaises(ValueError):
            kv.base64_value("nonexistent")

    def test_yaml_value(self):
        data = {"key": "value"}
        yaml_str = yaml.safe_dump(data)
        encoded = base64.b64encode(yaml_str.encode()).decode()
        kv = KeyVal({"value": encoded})
        result = kv.yaml_value()
        self.assertEqual(result, data)

    def test_yaml_value_dump(self):
        data = {"key": "value"}
        yaml_str = yaml.safe_dump(data)
        encoded = base64.b64encode(yaml_str.encode()).decode()
        kv = KeyVal({"value": encoded})
        result = kv.yaml_value_dump()
        self.assertIsInstance(result, str)


class TestKeyValBuilder(unittest.TestCase):
    def test_builder_add(self):
        builder = KeyValBuilder()
        result = builder.add("test.key", "value")
        self.assertIs(result, builder)

    def test_builder_remove(self):
        builder = KeyValBuilder()
        builder.add("test.key", "value")
        result = builder.remove("test.key")
        self.assertIs(result, builder)

    def test_builder_info(self):
        builder = KeyValBuilder()
        metadata = {"created_by": "test"}
        result = builder.info(metadata)
        self.assertIs(result, builder)

    def test_builder_build(self):
        kv = (KeyValBuilder()
              .add("user.name", "test")
              .add("user.age", 25)
              .info({"created_by": "test"})
              .build())

        self.assertIsInstance(kv, KeyVal)
        self.assertEqual(kv.get_value("user.name"), "test")
        self.assertEqual(kv.get_value("user.age"), 25)
        self.assertEqual(kv.info, {"created_by": "test"})


if __name__ == '__main__':
    unittest.main()
