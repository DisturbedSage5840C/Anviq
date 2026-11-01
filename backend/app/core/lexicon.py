"""Words and text clean-up shared by intent parsing and language detection.

Teachers type Hindi in English letters ("haan", "nahi"), type Marathi or Tamil from a Google Indic
keyboard, and stretch words ("haaan"). Everything here is for *understanding* what was typed; the
language the coach replies in is the teacher's own setting and nothing here changes it.
"""

import re
import unicodedata

# Every Indic block from Devanagari to Malayalam (U+0900-U+0D7F) except the danda (U+0964) and
# double danda (U+0965), which are punctuation. Python's \w misses the vowel signs, so the range is
# listed rather than relying on it.
_TOKEN = re.compile(r"[\w\u0900-\u0963\u0966-\u0D7F]+")
# Zero-width joiner and non-joiner: Indic keyboards insert them inside conjuncts.
_JOINERS = dict.fromkeys((0x200C, 0x200D))
_STRETCHED = re.compile(r"(.)\1{2,}")


def normalise(text: str) -> str:
    """NFC, case-folded, without zero-width joiners."""
    return unicodedata.normalize("NFC", text).translate(_JOINERS).casefold()


def tokenise(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(normalise(text)))


def squeezed(token: str) -> tuple[str, ...]:
    """A token, then its stretched-letter forms: "haaan" gives "haaan", "haan", "han".

    Only runs of three or more letters are touched, so real doubles ("theek", "accha") stay put.
    """
    if not _STRETCHED.search(token):
        return (token,)
    to_two = _STRETCHED.sub(r"\1\1", token)
    to_one = _STRETCHED.sub(r"\1", token)
    return (token, to_two, to_one)


def in_lexicon(token: str, words: frozenset[str]) -> bool:
    return any(form in words for form in squeezed(token))


def words(text: str) -> frozenset[str]:
    return frozenset(tokenise(text))


# --- Hindi typed in English letters -------------------------------------------------------------
ROMAN_YES = words(
    "haan han haa haanji haanjee ji jee theek thik bilkul zaroor sahi accha achha acha"
)
ROMAN_NO = words("nahi nahin naheen nahee nai na")
ROMAN_QUESTION = words(
    "kya kaise kaisa kaisi kyun kyu kyon kab kahan kahaan kaun kitna kitne kitni kis kisko"
)
# Hindi words that are not also everyday English words ("main", "to", "me", "is" are left out).
ROMAN_HINDI = (
    ROMAN_YES
    | ROMAN_NO
    | ROMAN_QUESTION
    | words(
        """hai hain hoon ho tha thi mujhe mera meri mere aap aapko aapka aapki tum tumhe yeh ye woh
    wo vo isse usse isko usko bacche bachche bachon bacchon baccha padhna padhana padhaya
    padhte padhta sikhana sikhaun sikhao seekh seekhna seekhte samajh samjhao samjhana batao
    bataiye bataye bolo karo karna kare karu karun karein kijiye chahiye chahta chahti bahut
    bohot thoda zyada jyada kam aur lekin magar kyunki agar toh ko ka ki ke se mein mai
    hamare hamara apne apna kuch koi sab sabhi abhi kal aaj phir fir wala wali wale raha
    rahi rahe sakta sakti sakte paate paata paati pata dena dijiye lena lijiye ghatana jodna
    jod guna bhag ganit shiksha kaksha pathyakram shikshak adhyapak keh kehna""".replace("\n", " ")
    )
)
ENGLISH_FUNCTION = words(
    """the a an is are was were am be been to of in on at for with and or but not this that these
    those it i you we they he she my your our their do does did how what why when where which who
    can could should would will shall may have has had please yes no from by about into so if then
    than there here some any all more most very too also just only""".replace("\n", " ")
)

# --- Devanagari: Hindi against Marathi (the two share the script) --------------------------------
HINDI_DEVANAGARI = words(
    """है हैं हूँ हूं था थी थे नहीं नही क्या कैसे कैसी क्यों कब कहाँ कहां कौन कितना कितने कितनी
    मुझे मैं आप और लेकिन को की के में से पर यह वह ये वो बच्चे बच्चों चाहिए सकते सकता सकती रहा
    रही रहे करो कीजिए बताइए समझ पढ़ाना सिखाना घटाना जोड़ गुणा भाग कक्षा पाठ योजना हाँ हां जी
    ठीक""".replace("\n", " ")
)
MARATHI_DEVANAGARI = words(
    """आहे आहेत नाही नाहीत काय कसे कशी कसा कधी कुठे कोण किती कोणता मला तुला तुम्ही आम्ही आणि पण
    होय मुलांना मुले मुलं शिकवावी शिकवा सांगा द्या करा समजत समजावून वजाबाकी बेरीज गुणाकार
    भागाकार धडा वर्ग माझ माझा माझी माझे तुमचा त्याला त्यांना इथे असे असा असते""".replace("\n", " ")
)

# --- Question words in scripts other than Devanagari-Hindi --------------------------------------
# Hindi's own list lives in intents.py. "का" (Marathi: why) is left out because in Hindi it means
# "of".
QUESTION_WORDS_OTHER = words(
    """काय कसे कशी कसा कधी कुठे कोण किती कोणता
    என்ன ஏன் எப்படி எப்போது எங்கே யார் எவ்வளவு
    কী কি কেন কীভাবে কিভাবে কখন কোথায় কে কত
    ఏమిటి ఎందుకు ఎలా ఎప్పుడు ఎక్కడ ఎవరు ఎంత
    ಏನು ಏಕೆ ಹೇಗೆ ಯಾವಾಗ ಎಲ್ಲಿ ಯಾರು ಎಷ್ಟು
    എന്ത് എന്തുകൊണ്ട് എങ്ങനെ എപ്പോൾ എവിടെ ആര് എത്ര
    શું કેમ કેવી ક્યારે ક્યાં કોણ કેટલું
    ਕੀ ਕਿਉਂ ਕਿਵੇਂ ਕਦੋਂ ਕਿੱਥੇ ਕੌਣ ਕਿੰਨਾ
    କଣ କାହିଁକି କିପରି କେବେ କେଉଁଠି କିଏ କେତେ""".replace("\n", " ")
)
