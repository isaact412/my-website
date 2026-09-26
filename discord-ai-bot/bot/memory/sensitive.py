"""Blocks memories about sensitive or private personal things before they're saved.

This is a safety net on top of the AI's own instructions (small local models often ignore
those). False positives just mean a harmless memory gets dropped, which is fine: the bot
should remember games, bits and lore, not people's private lives.
"""
import re

_PATTERNS = [
    # physical & mental health
    r"\b(depress\w*|anxiety|anxious|panic|adhd|autis\w*|bipolar|diagnos\w*|therap(y|ist)|medication|meds|"
    r"pregnan\w*|cancer|disease|illness|disorder|surgery|rehab|suicid\w*|self[- ]harm|eating disorder|"
    r"mental health|breakdown|trauma\w*|ocd|ptsd|sick|injur\w*)\b",
    # feelings / emotional state
    r"\b(heartbr\w*|broken heart|hurt|pain\w*|sad|sadness|upset|crying|cried|lonely|loneliness|grief|griev\w*|"
    r"feelings?|emotional\w*|stressed|stress|insecur\w*|jealous\w*|vulnerable|struggl\w*|miss(es|ing)? (him|her|them|their)|"
    r"misses)\b",
    # romance / dating / sex life
    r"\b(romantic\w*|romance|dating|dated|girlfriend|boyfriend|gf|bf|crush|ex|exes|breakup|broke up|hook(ed|ing)? up|"
    r"kiss\w*|hug\w*|virgin\w*|sex life|single|in love|relationship status|cheat\w*)\b",
    # sexual content about a person
    r"\b(sex|sexual\w*|lube|condoms?|porn\w*|horny|masturbat\w*|nudes?|naked|onlyfans|dick|penis|pussy|vagina|boobs|"
    r"cum|orgasm\w*|fetish\w*|kink\w*)\b",
    # family & home life
    r"\b(dad|mom|mother|father|parents?|stepdad|stepmom|brother|sister|grandma|grandpa|grandparents?|family|divorce\w*)\b",
    # religion
    r"\b(religio\w*|christian|catholic|muslim|islam\w*|jewish|judaism|hindu|buddhis\w*|atheis\w*|church|mosque|synagogue|pray\w*)\b",
    # sexuality / gender identity
    r"\b(gay|lesbian|bisexual|queer|transgender|trans (guy|girl|man|woman)|sexuality|closeted|coming out)\b",
    # politics
    r"\b(democrat\w*|republican\w*|liberal|conservative|leftist|right[- ]wing|left[- ]wing|voted for|votes for|"
    r"political views?|maga|abortion)\b",
    # ethnicity / immigration
    r"\b(ethnicity|race is|is (black|white|asian|hispanic|latino|latina|mexican|arab)|immigra\w*|undocumented|deport\w*)\b",
    # private info & location
    r"\b(home address|address|lives in|lives at|moved to|moving to|hometown|phone number|social security|password|"
    r"salary|in debt|his house|her house|their house)\b",
]
_SENSITIVE = re.compile("|".join(_PATTERNS), re.I)


def is_sensitive(text: str) -> bool:
    return bool(_SENSITIVE.search(text))
