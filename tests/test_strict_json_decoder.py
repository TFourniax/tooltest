from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor

from diffwitness.json_contract import strict_json_loads


class StrictDecoderTests(unittest.TestCase):
    def test_documents_and_failed_parses_do_not_share_mutable_state(self):
        raw = '{"same":{"same":["é",1]},"other":{"same":2}}'
        first = strict_json_loads(raw)
        first['same']['same'].append('caller mutation')
        invalid = ['{"same":0,"same":1}', '{"same":0,"\\u0073ame":1}',
                   '{"nested":{"key":1,"key":2}}', 'NaN', 'Infinity', '-Infinity',
                   '{', '[0] trailing', '\ufeff{}']
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                strict_json_loads(value)
            self.assertEqual(strict_json_loads(raw), json.loads(raw))

    def test_encoding_and_type_compatibility(self):
        raw = '{"mémoire":[1,2,3]}'
        for encoding in ('utf-8', 'utf-8-sig', 'utf-16', 'utf-32'):
            for wrap in (bytes, bytearray):
                value = wrap(raw.encode(encoding))
                with self.subTest(encoding=encoding, wrap=wrap):
                    self.assertEqual(strict_json_loads(value), json.loads(value))
        for value in (None, 1, [], {}):
            with self.subTest(value=value), self.assertRaises(TypeError):
                strict_json_loads(value)

    def test_concurrent_documents_and_rejections_remain_independent(self):
        def decode(index):
            raw = json.dumps({'shared': {'index': index}, 'unicode': 'é𐀀'})
            for _ in range(20):
                self.assertEqual(strict_json_loads(raw), json.loads(raw))
                with self.assertRaises(ValueError):
                    strict_json_loads('{"shared":0,"shared":1}')
            return strict_json_loads(raw)['shared']['index']
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(decode, range(32))), list(range(32)))


if __name__ == '__main__':
    unittest.main()
