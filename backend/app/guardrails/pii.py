"""Scrubs personal data from teacher transcripts before anything is persisted.

Teachers are told not to name pupils, but they do. Contact details and a list of common
first names are replaced with placeholders. Riya, Aman and Meena are our AI children, so
they are never touched. The name list is a deliberate floor, not a guarantee.
"""

import re

PHONE_PLACEHOLDER = "[phone]"
ID_PLACEHOLDER = "[id]"
EMAIL_PLACEHOLDER = "[email]"
CHILD_PLACEHOLDER = "[बच्चा]"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9६-९]\d{4}[\s-]?\d{5}(?!\d)")
_AADHAAR = re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)")

# Excludes the AI children (riya, aman, meena and their Devanagari spellings).
_CHILD_NAMES = (
    "pinky", "rahul", "sonu", "ravi", "raju", "anita", "suresh", "priya", "pooja", "sunil",
    "mohan", "geeta", "kavita", "deepak", "manoj", "neha", "rohit", "sita", "gopal", "lakshmi",
    "पिंकी", "राहुल", "सोनू", "रवि", "राजू", "अनीता", "सुरेश", "प्रिया", "पूजा", "सुनील",
    "मोहन", "गीता", "कविता", "दीपक", "मनोज", "नेहा", "रोहित", "सीता", "गोपाल", "लक्ष्मी",
)  # fmt: skip
_WORD_EDGE = r"\wऀ-ॿ"
_CHILD_NAME = re.compile(
    rf"(?<![{_WORD_EDGE}])(?:{'|'.join(map(re.escape, _CHILD_NAMES))})(?![{_WORD_EDGE}])",
    re.IGNORECASE,
)


def scrub(text: str) -> str:
    text = _EMAIL.sub(EMAIL_PLACEHOLDER, text)
    text = _PHONE.sub(PHONE_PLACEHOLDER, text)
    text = _AADHAAR.sub(ID_PLACEHOLDER, text)
    return _CHILD_NAME.sub(CHILD_PLACEHOLDER, text)
