import unittest

from pylabview.typesystem import (
    ARRAY, BOOLEAN, ERROR, NUMERIC, VARIANT, WAVEFORM, ErrorCluster, Waveform,
    coerce, compatible, deserialize, infer_type, serialize, validate,
)


class TypeSystemTests(unittest.TestCase):
    def test_infer_distinguishes_bool_from_numeric(self):
        self.assertEqual(infer_type(True), BOOLEAN)
        self.assertEqual(infer_type(2.5), NUMERIC)

    def test_variant_is_compatible_with_every_type(self):
        self.assertTrue(compatible(NUMERIC, VARIANT))
        self.assertTrue(compatible(VARIANT, ERROR))
        self.assertFalse(compatible(NUMERIC, BOOLEAN))

    def test_numeric_does_not_coerce_boolean(self):
        with self.assertRaises(TypeError):
            coerce(True, NUMERIC)

    def test_array_coercion_copies_tuple(self):
        self.assertEqual(coerce((1, 2), ARRAY), [1, 2])

    def test_waveform_validation(self):
        waveform = Waveform(0, 0.1, [1, 2.5])
        self.assertTrue(validate(waveform, WAVEFORM))
        with self.assertRaises(ValueError):
            Waveform(0, 0, [1])

    def test_error_cluster_round_trip(self):
        error = ErrorCluster(True, 42, "sensor")
        self.assertEqual(deserialize(serialize(error)), error)

    def test_waveform_round_trip(self):
        waveform = Waveform(1, 0.5, [2, 3])
        self.assertEqual(deserialize(serialize(waveform)), waveform)


if __name__ == "__main__":
    unittest.main()
