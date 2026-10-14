"""Audio Speech-to-Text module for ELI"""

import speech_recognition as sr
import threading
import queue
import time
import os


# Speech to text on this machine (Whisper through faster-whisper); recordings never leave it.
# ELI_WHISPER (model size, default base), ELI_WHISPER_DEVICE (cpu/cuda), ELI_WHISPER_LANG (default en; empty = detect)
_whisper = None
_whisper_lock = threading.Lock()


def _whisper_model():
    global _whisper
    with _whisper_lock:
        if _whisper is None:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(
                os.environ.get("ELI_WHISPER", "base"),
                device=os.environ.get("ELI_WHISPER_DEVICE", "cpu"),
                compute_type=os.environ.get("ELI_WHISPER_COMPUTE", "int8"),
            )
        return _whisper


def transcribe(audio: sr.AudioData) -> str:
    """The words in a recording. Raises sr.UnknownValueError when nothing was said and
    sr.RequestError when the speech model cannot load, as SpeechRecognition's recognizers do."""
    import numpy as np
    try:
        model = _whisper_model()
    except Exception as e:
        raise sr.RequestError(f"local speech model unavailable: {e}") from e
    pcm = audio.get_raw_data(convert_rate=16000, convert_width=2)
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _info = model.transcribe(samples, language=os.environ.get("ELI_WHISPER_LANG", "en") or None,
                                       vad_filter=True)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    if not text:
        raise sr.UnknownValueError()
    return text

class ELIAudioSTT:
    """Entropic Logical Interpreter Audio Input System"""
    
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.is_listening = False
        self.audio_queue = queue.Queue()
        self.last_transcript = ""
        
        # Calibrate for ambient noise
        print("[AUDIO] Calibrating microphone for ambient noise...")
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
        print("[AUDIO] Microphone calibration complete")
    
    def start_listening(self, callback=None):
        """Start continuous listening in background thread."""
        if self.is_listening:
            print("[AUDIO] Already listening")
            return False
        
        self.is_listening = True
        self.callback = callback
        
        # Start listening thread
        self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listen_thread.start()
        
        print("[AUDIO] Started listening for voice commands")
        return True
    
    def stop_listening(self):
        """Stop continuous listening."""
        self.is_listening = False
        print("[AUDIO] Stopped listening")
    
    def _listen_loop(self):
        """Main listening loop."""
        with self.microphone as source:
            print("[AUDIO] Microphone ready")
            
            while self.is_listening:
                try:
                    # Listen for audio
                    print("[AUDIO] Listening... (say 'ELI' to activate)")
                    audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
                    
                    # Try to recognize speech
                    try:
                        transcript = transcribe(audio).lower()
                        print(f"[AUDIO] Heard: {transcript}")
                        
                        # Check for wake word
                        if "eli" in transcript or "hey eli" in transcript:
                            print("[AUDIO] Wake word detected! Listening for command...")
                            
                            # Listen for command
                            command_audio = self.recognizer.listen(source, timeout=3, phrase_time_limit=10)
                            command_text = transcribe(command_audio)
                            
                            print(f"[AUDIO] Command: {command_text}")
                            self.last_transcript = command_text
                            
                            # Call callback if provided
                            if self.callback:
                                self.callback(command_text)
                            
                        # Store in queue
                        self.audio_queue.put(transcript)
                        
                    except sr.UnknownValueError:
                        print("[AUDIO] Could not understand audio")
                    except sr.RequestError as e:
                        print(f"[AUDIO] Recognition error: {e}")
                    
                except sr.WaitTimeoutError:
                    # Timeout, continue listening
                    continue
                except Exception as e:
                    print(f"[AUDIO] Error: {e}")
                    time.sleep(1)
    
    def listen_once(self, timeout=5):
        """Listen once and return transcript."""
        try:
            with self.microphone as source:
                print("[AUDIO] Listening for command...")
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=10)
                
                transcript = transcribe(audio)
                print(f"[AUDIO] Command: {transcript}")
                self.last_transcript = transcript
                
                return transcript
                
        except sr.UnknownValueError:
            print("[AUDIO] Could not understand audio")
            return None
        except sr.RequestError as e:
            print(f"[AUDIO] Recognition error: {e}")
            return None
        except sr.WaitTimeoutError:
            print("[AUDIO] Listening timeout")
            return None
        except Exception as e:
            print(f"[AUDIO] Error: {e}")
            return None
    
    def get_last_transcript(self):
        """Get last successful transcript."""
        return self.last_transcript
    
    def clear_queue(self):
        """Clear audio queue."""
        while not self.audio_queue.empty():
            self.audio_queue.get()

# Global instance
_audio_stt_instance = None

def get_audio_stt():
    """Get singleton audio STT instance."""
    global _audio_stt_instance
    if _audio_stt_instance is None:
        _audio_stt_instance = ELIAudioSTT()
    return _audio_stt_instance

def start_audio_listening(callback=None):
    """Start audio listening."""
    return get_audio_stt().start_listening(callback)

def stop_audio_listening():
    """Stop audio listening."""
    get_audio_stt().stop_listening()

def listen_for_command(timeout=5):
    """Listen for a single command."""
    return get_audio_stt().listen_once(timeout)

def get_last_command():
    """Get last recognized command."""
    return get_audio_stt().get_last_transcript()
