"""Fixed teacher-facing messages sent before a conversation language is known.

Each is bilingual (Hindi, then English). Conversation copy moves to content/copy/*.yaml
with the router.
"""

UNSUPPORTED = "मैं अभी सिर्फ़ आवाज़ और टेक्स्ट समझती हूँ।\nFor now I only understand voice notes and text."
AUDIO_TOO_LONG = (
    "आपका वॉइस नोट थोड़ा लंबा है। कृपया 2 मिनट से छोटा नोट भेजें।\n"
    "That voice note is a bit long. Please send one under 2 minutes."
)
MEDIA_TOO_LARGE = (
    "यह फ़ाइल बहुत बड़ी है। कृपया छोटा वॉइस नोट भेजें।\n"
    "That file is too large. Please send a shorter voice note."
)
CANNOT_HEAR = (
    "मैं आपकी आवाज़ ठीक से सुन नहीं पाई। कृपया दोबारा बोलें या टाइप करें।\n"
    "I couldn't hear that clearly. Please say it again or type it."
)
VOICE_UNAVAILABLE = (
    "अभी मैं वॉइस नोट नहीं सुन सकती। कृपया टेक्स्ट में लिखें।\n"
    "I can't listen to voice notes right now. Please type your message."
)
