"""Word banks and word maps behind the literacy misconceptions.

Plain data, written by hand so a teacher or reviewer can read every entry. The banks are what the
registry draws reading and spelling problems from; the rules decide which words they apply to.
"""

VOWELS = "aeiou"

# Short consonant-vowel-consonant words, for blending and decoding.
CVC_WORDS = (
    "cat", "dog", "sun", "pen", "pig", "hat", "bus", "cup", "bed", "bag", "net", "mud", "hen",
    "jam", "box", "pin", "map", "log", "rug", "lid",
)  # fmt: skip

# Words a child who confuses b and d will misread.
BD_WORDS = ("bed", "bad", "dad", "bag", "big", "dig", "dip", "bus", "bud", "bat", "dot", "dub")

# Hindi words with the look-alike letters ब and व.
HINDI_BV_WORDS = ("बकरी", "बतख", "बादल", "बहन", "वन", "वर्षा", "बगीचा")

# Words read back to front: was/saw, on/no.
REVERSED_WORDS = {
    "was": "saw", "saw": "was", "on": "no", "no": "on", "top": "pot", "pot": "top",
    "tap": "pat", "pat": "tap", "but": "tub", "tub": "but", "ten": "net", "net": "ten",
    "rat": "tar", "tar": "rat",
}  # fmt: skip

# Words guessed from their first letter and overall shape, not read letter by letter.
SHAPE_GUESSES = {
    "they": "then", "what": "want", "were": "where", "said": "sad", "when": "went",
    "from": "form",
}  # fmt: skip

# Words spelled the way they sound.
PHONETIC_SPELLINGS = {
    "friend": "frend", "said": "sed", "because": "becos", "people": "peple", "school": "skool",
    "would": "wud", "again": "agen", "answer": "anser",
}  # fmt: skip

# Plurals of words ending in a consonant plus y.
PLURAL_Y_WORDS = ("babies", "puppies", "cities", "ladies", "berries", "stories", "flies", "bodies")

# Words whose last consonant is doubled before -ing or -ed.
DOUBLED_CONSONANT_WORDS = (
    "running", "stopped", "sitting", "planning", "begged", "swimming", "dropped", "clapped",
)  # fmt: skip

# Words that lose their silent e before -ing.
SILENT_E_WORDS = ("hoping", "making", "taking", "writing", "riding", "smiling", "giving", "using")

READ_WORDS = tuple(
    dict.fromkeys((*CVC_WORDS, *BD_WORDS, *HINDI_BV_WORDS, *REVERSED_WORDS, *SHAPE_GUESSES))
)
SPELL_WORDS = tuple(
    dict.fromkeys((*PHONETIC_SPELLINGS, *PLURAL_Y_WORDS, *DOUBLED_CONSONANT_WORDS, *SILENT_E_WORDS))
)
