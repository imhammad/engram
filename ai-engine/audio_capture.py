import os
import tempfile

import fake_models
from paths import whisper_path

SAMPLE_RATE = 16000
RECORD_SECONDS = 8

if not fake_models.enabled():
    import sounddevice as sd
    from faster_whisper import WhisperModel
    from scipy.io.wavfile import write as write_wav

    print("Loading local speech-to-text model, this may take a moment...")
    _whisper_model = WhisperModel(str(whisper_path()), device="cpu", compute_type="int8")
    print("Speech-to-text model loaded successfully.")


def record_and_transcribe() -> str:
    if fake_models.enabled():
        return fake_models.transcribe()
    print(f"Recording for {RECORD_SECONDS} seconds...")
    recording = sd.rec(
        int(RECORD_SECONDS * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    print("Recording finished, transcribing...")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
        tmp_path = tmp_file.name
        write_wav(tmp_path, SAMPLE_RATE, recording)

    try:
        segments, _ = _whisper_model.transcribe(tmp_path)
        transcript = " ".join(segment.text.strip() for segment in segments)
    finally:
        os.remove(tmp_path)

    return transcript.strip()