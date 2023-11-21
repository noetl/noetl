import unittest
from keyval import KeyVal
import base64
import json

class TestKeyVal(unittest.TestCase):

    def test_get_keys(self):
        kv = KeyVal({"a": 1, "b": 2})
        self.assertListEqual(kv.get_keys(), ["a", "b"])

    def test_get_value(self):
        kv = KeyVal({"a": {"b": {"c": 10}}})
        self.assertEqual(kv.get_value("a.b.c"), 10)
        self.assertIsNone(kv.get_value("a.b.d"))
        self.assertEqual(kv.get_value("a.b.d", default=5), 5)
        with self.assertRaises(TypeError):
            kv.get_value("a.b")

    def test_set_value(self):
        kv = KeyVal()
        kv.set_value("a.b.c", 10)
        self.assertEqual(kv.get_value("a.b.c"), 10)
        with self.assertRaises(TypeError):
            kv.set_value(None, 10)
        with self.assertRaises(ValueError):
            kv.set_value("a.b", [])

    def test_to_json(self):
        kv = KeyVal({"a": 1, "b": 2})
        json_repr = kv.to_json()
        self.assertIsInstance(json_repr, bytes)
        self.assertEqual(json.loads(json_repr.decode('utf-8')), {"a": 1, "b": 2})
        with self.assertRaises(ValueError):
            KeyVal({"a": {1: "invalid"}}).to_json()

    def test_base64_path(self):
        kv = KeyVal({"workflow_base64": base64.b64encode("test".encode()).decode()})
        self.assertEqual(kv.base64_path(), base64.b64encode("test".encode()).decode())
        with self.assertRaises(ValueError):
            kv.base64_path("nonexistent")

    def test_encode(self):
        kv = KeyVal({"a": 1})
        encoded = kv.encode()
        self.assertIsInstance(encoded, bytes)

    def test_yaml_value(self):
        kv = KeyVal({"value": base64.b64encode(json.dumps({"a": 1}).encode()).decode()})
        self.assertEqual(kv.yaml_value(), {"a": 1})

    def test_decode(self):
        kv = KeyVal({"a": 1})
        encoded = kv.encode()
        decoded = KeyVal.decode(encoded)
        self.assertEqual(decoded, {"a": 1})

    def test_base64_str(self):
        self.assertEqual(KeyVal.base64_str("test"), base64.b64encode("test".encode()).decode())

    def test_base64_yaml(self):
        yaml_str = base64.b64encode(json.dumps({"a": 1}).encode()).decode()
        self.assertEqual(KeyVal.base64_yaml(yaml_str), {"a": 1})

    def test_from_json(self):
        json_str = json.dumps({"a": 1})
        kv = KeyVal.from_json(json_str)
        self.assertEqual(kv, {"a": 1})
        with self.assertRaises(ValueError):
            KeyVal.from_json("invalid json")

if __name__ == '__main__':
    unittest.main()
