"""An offline stand-in for edge_tts.Communicate so tests never reach the TTS service."""

import subprocess
from unittest import mock


def sine_mp3(seconds: float = 2.0) -> bytes:
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={seconds}", "-c:a", "libmp3lame", "-b:a", "64k",
         "-f", "mp3", "pipe:1"],
        capture_output=True, check=True, stdin=subprocess.DEVNULL)
    return result.stdout


def fake_edge_tts(test_case, audio: bytes = None, error: BaseException = None) -> list:
    """Patch edge_tts.Communicate for the test; returns the list of calls made."""
    import edge_tts

    calls: list = []
    state = {"audio": sine_mp3() if audio is None else audio, "error": error}

    class Communicate:
        def __init__(self, text, voice, rate=None, boundary=None):
            self.text = text
            calls.append({"text": text, "voice": voice, "rate": rate})

        async def stream(self):
            if state["error"] is not None:
                raise state["error"]
            tokens = [self.text[index:index + 2] for index in range(0, len(self.text), 2)]
            for index, token in enumerate(tokens):
                yield {"type": "WordBoundary", "text": token,
                       "offset": (250 + index * 500) * 10000, "duration": 350 * 10000}
            yield {"type": "audio", "data": state["audio"]}

    patcher = mock.patch.object(edge_tts, "Communicate", Communicate)
    patcher.start()
    test_case.addCleanup(patcher.stop)
    return calls

