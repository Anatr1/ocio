"""Test-process-only fault hook. No GPIO/CSI writes and no production source edits.

Activate only by adding this directory to PYTHONPATH for the temporary test node.
The marker makes OpenCV reads fail so the existing CameraSource reopen path runs.
"""
from pathlib import Path
import cv2

_capture = cv2.VideoCapture
_marker = Path('/tmp/occhio-cam0-read-failure')

class ReadFaultCapture:
    def __init__(self, *args, **kwargs):
        self.inner = _capture(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def read(self, *args, **kwargs):
        if _marker.exists():
            return False, None
        return self.inner.read(*args, **kwargs)

cv2.VideoCapture = ReadFaultCapture
