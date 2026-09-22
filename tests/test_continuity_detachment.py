from __future__ import annotations

import copy
import math
import unittest

import diffwitness.continuity_events as events


class DetachmentTests(unittest.TestCase):
    def test_json_values_preserve_types_and_detach_nested_mutability(self):
        value = {'none': None, 'bool': True, 'integer': 1, 'float': -0.0,
                 'unicode': 'Mémoire 🧪', 'nested': [{'keys': [1, 2]}]}
        result = events._detach_json(value)
        self.assertEqual(result, copy.deepcopy(value))
        self.assertIs(type(result['bool']), bool)
        self.assertIs(type(result['integer']), int)
        self.assertEqual(math.copysign(1, result['float']), -1)
        result['nested'][0]['keys'].append(3)
        self.assertEqual(value['nested'][0]['keys'], [1, 2])

    def test_shared_aliases_and_cycles_match_deepcopy(self):
        shared = [1]
        value = {'first': shared, 'second': shared}
        value['cycle'] = value
        result = events._detach_json(value)
        self.assertIs(result['first'], result['second'])
        self.assertIs(result['cycle'], result)
        self.assertIsNot(result, value)
        self.assertIsNot(result['first'], shared)

    def test_tuple_fallback_shares_one_memo_with_json_containers(self):
        shared = []
        pair = (shared,)
        value = [pair, shared, pair]
        shared.append(value)
        result = events._detach_json(value)
        self.assertIs(type(result[0]), tuple)
        self.assertIs(result[0], result[2])
        self.assertIs(result[0][0], result[1])
        self.assertIs(result[1][0], result)
        self.assertIsNot(result[1], shared)

    def test_subclasses_retain_existing_deepcopy_behavior(self):
        class CustomDict(dict):
            calls = 0
            def __deepcopy__(self, memo):
                type(self).calls += 1
                result = CustomDict()
                memo[id(self)] = result
                result['shared'] = copy.deepcopy(self['shared'], memo)
                return result
        shared = []
        custom = CustomDict(shared=shared)
        value = [shared, custom, custom]
        result = events._detach_json(value)
        self.assertIs(type(result[1]), CustomDict)
        self.assertIs(result[0], result[1]['shared'])
        self.assertIs(result[1], result[2])
        self.assertEqual(CustomDict.calls, 1)

    def test_subclass_memo_overrides_for_atomic_values_follow_runtime_deepcopy(self):
        # CPython 3.11-3.13 consult memo before atom dispatch; 3.14 does not.
        # Delegate the uncommon override case rather than assuming a version.
        for atom in (None, False, True, 173, 1.75, 'memo-bound scalar'):
            with self.subTest(atom=atom):
                replacement = ['memo replacement']
                class MemoWriter(dict):
                    def __deepcopy__(self, memo):
                        memo[id(atom)] = replacement
                        result = {'copied': True}
                        memo[id(self)] = result
                        return result
                value = [MemoWriter(), atom]
                expected = copy.deepcopy(value)
                actual = events._detach_json(value)
                self.assertEqual(actual, expected)
                self.assertIs(type(actual[1]), type(expected[1]))


if __name__ == '__main__':
    unittest.main()
