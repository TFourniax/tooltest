from __future__ import annotations

import json
import unittest
from pathlib import Path


class CertificateSchemaTests(unittest.TestCase):
    def test_unified_schema_declares_every_public_certificate_family(self) -> None:
        root = Path(__file__).resolve().parents[1]
        schema = json.loads(
            (root / "schema" / "diffwitness-certificate.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        defs = schema["$defs"]
        for name in ("exhaustive", "adaptive", "assurance", "validation", "notRequired"):
            self.assertIn(name, defs)
        patterns = json.dumps(schema)
        for prefix in ("dw2_", "dwac1_", "dwa1_", "dwv1_", "dw0_"):
            self.assertIn(prefix, patterns)


if __name__ == "__main__":
    unittest.main()
