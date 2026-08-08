"""Tests for voice input module"""
import unittest
from unittest.mock import MagicMock, patch
from plugin.voice import VoiceInput, get_voice_input


class MockSoundDevice:
    class InputStream:
        def __init__(self, **kwargs):
            self.callback = kwargs.get('callback')
            self.active = False
        def start(self):
            self.active = True
        def stop(self):
            self.active = False
        def close(self):
            pass


class MockMistralAI:
    class Mistral:
        def __init__(self, api_key=None):
            self.audio = MockAudio()

    class MockModel:
        pass


class MockAudio:
    class Transcriptions:
        def create(self, **kwargs):
            return MockResponse(kwargs.get('file', {}).get('content', b''))


class MockResponse:
    def __init__(self, audio_data):
        self.text = f"Test transcription for {len(audio_data)} bytes"


class TestVoiceInput(unittest.TestCase):
    def setUp(self):
        import plugin.voice as vm
        vm._voice_input = None

    @patch.dict('os.environ', {'MISTRAL_API_KEY': 'test-key'})
    @patch('sounddevice', new=MockSoundDevice())
    @patch('mistralai', new=MockMistralAI())
    def test_available(self):
        voice = VoiceInput()
        self.assertTrue(voice.is_available())

    @patch.dict('os.environ', {})
    @patch('sounddevice', new=MockSoundDevice())
    @patch('mistralai', new=MockMistralAI())
    def test_not_available_no_api_key(self):
        voice = VoiceInput()
        self.assertFalse(voice._has_api_key)
        self.assertFalse(voice.is_available())

    @patch('sounddevice', None)
    @patch('mistralai', None)
    @patch.dict('os.environ', {})
    def test_not_available_no_deps(self):
        voice = VoiceInput()
        self.assertFalse(voice.is_available())

    @patch.dict('os.environ', {'MISTRAL_API_KEY': 'test-key'})
    @patch('sounddevice', new=MockSoundDevice())
    @patch('mistralai', new=MockMistralAI())
    def test_get_voice_input_singleton(self):
        voice1 = get_voice_input()
        voice2 = get_voice_input()
        self.assertIs(voice1, voice2)


if __name__ == '__main__':
    unittest.main()
