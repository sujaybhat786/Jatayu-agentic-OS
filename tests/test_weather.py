import unittest
from jatayu.tools.weather import get_weather

class TestWeatherTool(unittest.TestCase):
    def test_get_weather_with_city(self):
        result = get_weather("Mysuru")
        self.assertIn("Weather in Mysuru", result)
        self.assertIn("°C", result)

    def test_get_weather_default_home(self):
        result = get_weather()
        self.assertTrue(result.startswith("Weather in Mysuru, India:") or result.startswith("Weather in"))
        self.assertIn("°C", result)

if __name__ == "__main__":
    unittest.main()
