"""Blocks memories about sensitive personal traits before they're ever saved.

This is a safety net on top of the AI's own instructions. False positives just mean
a harmless memory gets dropped, which is fine.
"""
import re

_PATTERNS = [
    # health
    r"\b(depress\w*|anxiety|adhd|autis\w*|bipolar|diagnos\w*|therap(y|ist)|medication|meds|pregnan\w*|cancer|disease|illness|disorder|surgery|rehab|suicid\w*|self[- ]harm|eating disorder)\b",
    # religion
    r"\b(religio\w*|christian|catholic|muslim|islam\w*|jewish|judaism|hindu|buddhis\w*|atheis\w*|church|mosque|synagogue)\b",
    # sexuality / gender identity / sex life
    r"\b(gay|lesbian|bisexual|queer|transgender|trans (guy|girl|man|woman)|sexuality|closeted|coming out|virgin|sex life|hooked up|nudes|onlyfans)\b",
    # politics
    r"\b(democrat\w*|republican\w*|liberal|conservative|leftist|right[- ]wing|left[- ]wing|voted for|votes for|political views?|maga|abortion)\b",
    # ethnicity / immigration
    r"\b(ethnicity|race is|is (black|white|asian|hispanic|latino|latina|mexican|arab)|immigra\w*|undocumented|deport\w*)\b",
    # private info
    r"\b(home address|lives at|phone number|social security|password|salary|in debt)\b",
]
_SENSITIVE = re.compile("|".join(_PATTERNS), re.I)


def is_sensitive(text: str) -> bool:
    return bool(_SENSITIVE.search(text))
