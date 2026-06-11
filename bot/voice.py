"""
Voice message transcription via faster-whisper (CPU).
Model downloads on first use (~75 MB for 'tiny', ~150 MB for 'base').
Set WHISPER_MODEL=base in .env for better accuracy at the cost of ~2x CPU time.
"""
import asyncio
import logging
import os
import tempfile

logger = logging.getLogger(__name__)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny")
_whisper = None


def _load_whisper():
    global _whisper
    if _whisper is None:
        try:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
            logger.info(f"Whisper model loaded: {WHISPER_MODEL}")
        except Exception as e:
            logger.warning(f"Whisper unavailable: {e}")
    return _whisper


def _transcribe_sync(audio_bytes: bytes, suffix: str) -> str | None:
    model = _load_whisper()
    if model is None:
        return None
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        segments, _ = model.transcribe(tmp_path, beam_size=1, language=None)
        text = " ".join(seg.text for seg in segments).strip()
        return text or None
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


async def transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str | None:
    """Async wrapper — runs CPU transcription in a thread pool."""
    suffix = ".ogg" if "ogg" in mime_type else ".mp3"
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _transcribe_sync, audio_bytes, suffix)
