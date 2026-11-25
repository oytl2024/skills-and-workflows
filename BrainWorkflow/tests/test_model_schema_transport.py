"""Offline provider-object contract and lossless optional-field transport tests."""
import json
import unittest

from wqb.semantic_compilation import _check_schema
from wqb.full_semantic_model_worker import strict_worker_schema, normalize_worker_answer


def assert_closed_provider_objects(schema):
    """Input: JSON schema dict. Output: None; reject objects missing provider-required property declarations."""
    if isinstance(schema, dict):
        if schema.get('type') == 'object':
            if schema.get('additionalProperties') is not False or set(schema.get('required', [])) != set(schema.get('properties', {})):
                raise AssertionError('provider object requires every property')
        for value in schema.values():
            assert_closed_provider_objects(value)
    elif isinstance(schema, list):
        for value in schema:
            assert_closed_provider_objects(value)


def wire_answer(schema, answer):
    """Input: canonical schema/value. Output: strict fake-provider value, retaining deliberate unknown properties."""
    if schema == {}:
        return json.dumps(answer)
    if 'anyOf' in schema:
        for branch in schema['anyOf']:
            try:
                _check_schema(branch, answer)
            except ValueError:
                continue
            return wire_answer(branch, answer)
        raise ValueError('fixture has no schema branch')
    if schema.get('type') == 'object':
        result = {key: wire_answer(value, answer[key]) if key in answer else None
                  for key, value in schema['properties'].items()}
        result.update({key: value for key, value in answer.items() if key not in schema['properties']})
        return result
    if schema.get('type') == 'array':
        return [wire_answer(schema['items'], value) for value in answer]
    return answer


class ModelSchemaTransportTests(unittest.TestCase):
    def test_all_initial_and_retrieval_wire_objects_declare_all_properties(self):
        from wqb.initial_research_planning import _output_schema
        from wqb.retrieval_research_planning import design_schema
        for canonical in [_output_schema(1), _output_schema(2, include_vector=True), design_schema()]:
            assert_closed_provider_objects(strict_worker_schema(canonical))

    def test_optional_reverse_roundtrip_absent_single_and_both_arms(self):
        from wqb.initial_research_planning import _output_schema
        schema = _output_schema(2)['properties']['tree']['properties']['nodes']['items']['properties']['reverse']
        reverse = dict(design_index=1, arm_id='baseline', interpretation='A hypothesis.', targets=[])
        for answer in ({}, {'baseline': reverse}, {'baseline': reverse, 'treatment': dict(reverse, arm_id='treatment')}):
            transported = wire_answer(schema, answer)
            self.assertEqual(normalize_worker_answer(schema, transported), answer)
        with self.assertRaises(ValueError):
            normalize_worker_answer(schema, dict(baseline=None))
