"""Application bootstrap for TeslaCamViewer.

This module is intentionally small and boring: it sets a few Qt Multimedia
environment defaults before Qt is imported, then constructs the main window.
Keeping the process bootstrap isolated here makes it easier to reason about
startup behavior without digging through the large viewer module.
"""

import os
import sys


# These environment defaults are applied before QApplication is created so Qt
# Multimedia picks predictable software-decoding behavior across machines.
os.environ.setdefault("QT_MEDIA_FFMPEG_ANALYZE_DURATION", "5000000")
os.environ.setdefault("QT_MEDIA_FFMPEG_PROBE_SIZE", "10000000")
os.environ.setdefault("QT_MEDIA_BACKEND", "FFMpeg")
os.environ.setdefault("QT_MEDIA_AUDIO_BACKEND", "none")
os.environ.setdefault("QT_MEDIA_DISABLE_HARDWARE_DECODING", "1")


def run() -> int:
    """Launch the Qt application and enter the event loop.

    Returns
    -------
    int
        The process exit code returned by ``QApplication.exec()``.
    """

    from PySide6.QtWidgets import QApplication

    from .viewer import TeslaCamViewer

    app = QApplication.instance() or QApplication(sys.argv)
    window = TeslaCamViewer()
    window.show()
    return app.exec()
