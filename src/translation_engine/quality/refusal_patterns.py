"""Shared LLM-refusal / meta-commentary detection patterns.

Single source of truth for HT-QUALITY-GATES-001 TC-QG-001's refusal-leak
gate (write_gate.py Gate 28) and scripts/quality/audit_llm_artifacts.py's
standalone post-hoc scan, which previously each risked drifting out of sync
(the same failure mode already seen with is_family_platform_index() being
reimplemented separately in scripts/quality/audit_all_content.py). Both now
import from here instead of maintaining their own copy of the phrase list.

Curated, deliberately broad multi-language refusal/meta-commentary phrase
list -- built from confirmed production instances (professionalize_llm
refusing/asking-for-clarification instead of translating, then that raw
response being shipped as page content) plus common equivalents in
languages this corpus covers. Matched case-insensitively as substrings.
See audit_llm_artifacts.py's original docstring for the discovery history
behind each block below -- kept verbatim here, not re-derived, since it is
already validated against real production defects.
"""
from __future__ import annotations

import re

REFUSAL_PHRASES: list[str] = [
    # confirmed instances
    "ich habe keine ahnung",
    "veuillez fournir le texte anglais",
    "cože",
    "validacija - molimo vas",
    # common "I don't know" equivalents
    "no tengo ni idea", "no sé", "não sei", "non lo so", "nie wiem",
    "nevím", "sconosciuto motivo", "ei tiedä", "vet inte", "geen idee",
    "не знам", "не знаю", "لا أعرف", "わかりません", "모르겠습니다",
    "hiçbir fikrim yok", "không biết",
    # "please provide the text" equivalents
    "please provide the", "por favor, proporcione", "bitte geben sie",
    "veuillez fournir", "si prega di fornire", "proszę podać",
    "por favor, forneça", "vänligen ange", "gelieve",
    # generic AI meta-commentary that should never appear in shipped content
    "as an ai", "i cannot translate", "i am unable to", "i'm unable to",
    "i don't have enough context", "please clarify",
    # Latvian (lv) -- added 2026-07-18, see audit_llm_artifacts.py history
    "man nav ne jausmas", "es nezinu", "nezinu, ko", "lūdzu, sniedziet",
    "lūdzu norādiet", "vai varat precizēt", "man nav pietiekami",
    # 2026-07-19 expansion, see audit_llm_artifacts.py history
    "أحتاج إلى النص الأصلي", "يرجى تزويدي بالنص", "يرجى تزويدي",
    "lütfen yorum eklemek istediğiniz metni sağlayın", "lütfen metni sağlayın",
    "请提供需要翻译的英文文本", "请提供需要翻译的",
    "번역할 텍스트를 제공해", "제공해 주시면",
    "vennligst oppgi den engelske teksten", "vennligst oppgi",
    "prašau pateikti tekstą", "ar galėtumėte pateikti tekstą",
    "कृपया वह अंग्रेज़ी पाठ प्रदान करें", "कृपया प्रदान करें",
    "mi serve il testo da tradurre", "per favore forniscimi il contenuto",
    "vă rog să furnizaţi textul", "vă rog să furnizați textul",
    "si us plau, proporcioneu el text", "si us plau, proporcioneu",
    "กรุณาให้ข้อความที่ต้องการแปล",
    "je potřeba text, který chcete přeložit",
    "prašom pateikti tekstą",
]

REFUSAL_RE = re.compile("|".join(re.escape(p) for p in REFUSAL_PHRASES), re.IGNORECASE)
LEADING_DASH_RE = re.compile(r"^[-–—]\s*\S")
ASPOSE_TOKEN_RE = re.compile(r"aspos[a-z]*", re.IGNORECASE)

# HT-QUALITY-GATES-001 Part 22 (1.6): shape-based conversational-response
# detection, added alongside promoting Gate 29 from "warn" to "block".
# REFUSAL_PHRASES above is a curated exact-substring list built from confirmed
# instances -- effective (it already independently caught 5 of 6 new leaked
# examples found this session, purely blocked by the gate's "warn"-only
# action, not a phrase-coverage gap) but necessarily incomplete: a fluent,
# non-templated conversational reply that doesn't happen to contain one of
# the curated phrases passes it untouched. One confirmed real miss:
# "I'm sorry, but I can't access or read any attached files. If you paste
# the text you'd like translated directly into the chat, I'll be happy to
# translate it for you." -- zero overlap with REFUSAL_PHRASES, published
# verbatim as page body content (docs.aspose.org/no/email/net/developer-guide
# /features.md). These patterns are deliberately generic first/second-person
# conversational-register markers that essentially never occur in this
# corpus's third-person technical-documentation prose, rather than more
# exact phrases -- broader net, same "never legitimately appears in Aspose
# API/product documentation" justification as REFUSAL_PHRASES itself.
CONVERSATIONAL_SHAPE_PATTERNS: list[str] = [
    r"\bi'?m sorry\b",
    r"\bi can'?t access\b",
    r"\bif you paste\b",
    r"\bi'?ll be happy to\b",
    r"\byou'?d like (it )?translated\b",
    r"\blet me know if\b",
    r"\bcould you (please )?(provide|give|share|clarify)\b",
    r"\bcan you (please )?(provide|give|share|clarify)\b",
    r"\bwould you (like|mind)\b",
    r"\bplease (provide|share|clarify|specify) (the|more)\b",
    r"\bi need (more|the) (context|information|text)\b",
    r"\bwhat (would you like|do you (want|mean))\b",
]
CONVERSATIONAL_SHAPE_RE = re.compile(
    "|".join(CONVERSATIONAL_SHAPE_PATTERNS), re.IGNORECASE
)
