import random
import unittest

from pylabview.drivers import ChannelConfig, DriverRegistry, SimulatedDAQDriver


class DriverTests(unittest.TestCase):
    def test_simulated_analog_read_is_in_range(self):
        driver = SimulatedDAQDriver(random.Random(1))
        driver.configure(ChannelConfig("AI0", "analog_input", 2, 3))
        self.assertTrue(2 <= driver.read("AI0") <= 3)

    def test_simulated_digital_write_and_readback(self):
        driver = SimulatedDAQDriver()
        driver.configure(ChannelConfig("DO0", "digital_output"))
        driver.write("DO0", True)
        self.assertTrue(driver.read("DO0"))

    def test_wrong_output_type_rejected(self):
        driver = SimulatedDAQDriver()
        driver.configure(ChannelConfig("DO0", "digital_output"))
        with self.assertRaises(TypeError):
            driver.write("DO0", 1)

    def test_registry_rejects_duplicate(self):
        registry = DriverRegistry.with_simulation()
        with self.assertRaises(ValueError):
            registry.register("simulated", SimulatedDAQDriver())


if __name__ == "__main__":
    unittest.main()
