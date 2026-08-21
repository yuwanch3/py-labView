import unittest
from unittest.mock import MagicMock
from pylabview.runtime import DataflowRuntime
from pylabview.model import Node
from pylabview.execution import RunSession
from pylabview.resources import ResourceManager
from pylabview.typesystem import ErrorCluster

class SpinningDropSequencerTests(unittest.TestCase):
    def setUp(self):
        self.clock_time = 0.0
        self.runtime = DataflowRuntime(clock=lambda: self.clock_time)
        self.session = RunSession(resources=ResourceManager())

    def evaluate_sequencer(self, inputs):
        node = Node("seq", "spinning_drop_sequencer", 0, 0, "Sequencer", 
                    {"rpm_list": [1000, 2000, 3000, 4000, 5000, 6000], "stage_duration": 180.0})
        return self.runtime._evaluate(node, inputs, {}, [], session=self.session)

    def test_sequencer_full_cycle(self):
        # Start
        inputs = {"start": True, "rpm_measured": 0, "sensor_status": "OK", 
                  "motor_error": ErrorCluster(), "capture_error": ErrorCluster()}
        # Add mock values for table row
        for p in ("rpm_measured", "diameter_px", "diameter_mm", "delta_rho", "omega_squared", "radius_cubed", "ift_N_m", "ift_mN_m"):
            inputs[p] = 1.0
            
        # Simulate 6 stages
        for i in range(6):
            res = self.evaluate_sequencer(inputs)
            self.assertEqual(res["state"], f"STAGE_{i}")
            # Advance time past 180s
            self.clock_time += 181.0
            res = self.evaluate_sequencer(inputs)
            self.assertEqual(len(res["table_data"]), i + 1)
        
        self.assertEqual(res["state"], "AWAITING_STOP")

    def test_sequencer_reset_on_stop(self):
        inputs = {"start": False, "rpm_measured": 0, "sensor_status": "OK", 
                  "motor_error": ErrorCluster(), "capture_error": ErrorCluster()}
        res = self.evaluate_sequencer(inputs)
        self.assertEqual(res["state"], "IDLE")

    def test_sequencer_error_halt(self):
        inputs = {"start": True, "rpm_measured": 0, "sensor_status": "NO_SENSOR", 
                  "motor_error": ErrorCluster(), "capture_error": ErrorCluster()}
        res = self.evaluate_sequencer(inputs)
        self.assertEqual(res["state"], "ERROR")
        self.assertTrue(res["error"].status)
