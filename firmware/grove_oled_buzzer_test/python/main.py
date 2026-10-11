"""Keep the hardware test app alive; cam0 belongs to the existing Linux service.

Do not open the camera here: two capture processes would compete for CAM0.
"""
from arduino.app_utils import App

App.run()
