# Adjudication Disagreements (stayed pending, not written)

## Arbitrated exceptions (3 of 50)

The 3 disagreements below involved one of the 6 originally-`approved`
registry entries, which left a real completeness gap
(`test_no_completeness_gaps_for_shipped_locales`). Since both sides in
each case made a checkable claim about internal consistency with sibling
headings already written for that same locale, a third-opinion arbiter
verified each claim directly against the locale's own other approved
values before accepting the adversarial counter-value:

- **hu / heading.methods**: adversarial counter "Metódusok" accepted over
  reviewer's "Módszerek" (wrong-sense trap: general "methods/ways" vs
  OOP-specific term) — written to `hu.yaml`.
- **id / heading.values**: adversarial counter "Nilai" accepted over
  reviewer's "Nilai-nilai" — verified id.yaml's sibling headings
  (Properti, Kelas, Antarmuka, Konstruktor) are ALL singular, no
  reduplication anywhere else — written to `id.yaml`.
- **ro / heading.description**: adversarial counter "Descriere" (no
  colon) accepted over reviewer's "Descriere:" — verified ro.yaml's
  sibling headings (Prezentare generală, Proprietăți, Metode) all lack a
  trailing colon — written to `ro.yaml`.

All other disagreements below remain genuinely PENDING per the mission's
"never force a tie-break guess" rule — they are non-core entries (pending
registry status, not one of the 6 originally-approved terms), so leaving
them unresolved does not create a completeness gap; they are candidates
for a future adjudication cycle or human arbiter.

## ar / heading.core_api
```json
{
  "locale": "ar",
  "id": "heading.core_api",
  "review_value": "واجهة التطبيقات الأساسية",
  "review_rationale": "Reasonably standard abbreviated Arabic rendering of 'Core API'; corpus majority is acceptable and the remaining candidates are unrelated cross-contamination noise.",
  "adversarial_counter": "واجهة برمجة التطبيقات الأساسية",
  "adversarial_rationale": "واجهة التطبيقات literally means only 'Applications Interface' — it drops برمجة (Programming), the core morpheme of the acronym API, whose established Arabic technical term (per Arabic Wikipedia and major vendor docs) is واجهة برمجة التطبيقات."
}
```

## bg / phrase.class_provides_methods
```json
{
  "locale": "bg",
  "id": "phrase.class_provides_methods",
  "review_value": "Този клас предоставя {n} метода за работа с обекти {api} в {platform} програми.",
  "review_rationale": "Plurality corpus form is grammatically sound Bulgarian (correct numeral count-form \"метода\") and preserves {n}/{api}/{platform} exactly, despite a highly fragmented vote distribution.",
  "adversarial_counter": "Този клас предоставя {n} метода за работа с {api} обекти в {platform} програми.",
  "adversarial_rationale": "Bulgarian avoids bare noun+noun juxtaposition (\"обекти {api}\" reads as incomplete/unnatural without a linking preposition); properly aggregating the raw corpus by structure across all {n}/{platform} variants (not just the single most literal string) shows \"{api} обекти\" -- placing the untranslatable class identifier immediately before \"обекти\", mirroring the source order -- is the true majority pattern (~64%) versus \"обекти {api}\" (~24%), and is also the more natural Bulgarian technical-writing convention."
}
```

## ca / phrase.is_a_class_in
```json
{
  "locale": "ca",
  "id": "phrase.is_a_class_in",
  "review_value": "{api} és una classe en Aspose.{family} FOSS per a {platform}.",
  "review_rationale": "Corpus top candidate already uses correct mid-sentence lowercase 'és' and the grammatically complete 'per a {platform}', matching standard Catalan syntax; all placeholders preserved.",
  "adversarial_counter": "{api} és una classe a Aspose.{family} FOSS per a {platform}.",
  "adversarial_rationale": "Catalan requires the locative preposition \"a\" (not \"en\") before an unmarked proper-noun product/organization name like \"Aspose.{family}\" (cf. \"treballa a Google\"), and the corpus itself is inconsistent -- the parallel is_an_enum_in entry correctly uses \"a Aspose.{family}\" -- showing \"en\" here is a Spanish-calque error despite its corpus dominance (295/294 votes)."
}
```

## ca / phrase.is_an_interface_in
```json
{
  "locale": "ca",
  "id": "phrase.is_an_interface_in",
  "review_value": "{api} és una interfície en Aspose.{family} FOSS per a {platform}.",
  "review_rationale": "Corpus top candidate has correct lowercase 'és' but is missing the required 'a' before {platform} ('per {platform}' instead of 'per a {platform}'); adding it matches the grammatically complete sibling phrases (class/struct) while preserving all placeholders.",
  "adversarial_counter": "{api} és una interfície a Aspose.{family} FOSS per a {platform}.",
  "adversarial_rationale": "Same Spanish-calque preposition error as is_a_class_in: Catalan needs \"a Aspose.{family}\", not \"en Aspose.{family}\", for a proper-noun product name, as the parallel enum template itself demonstrates."
}
```

## el / heading.core_api
```json
{
  "locale": "el",
  "id": "heading.core_api",
  "review_value": "Κεντρικό API",
  "review_rationale": "Corpus-dominant 'πυρήνα' is a bare accusative noun fragment (grammatically incomplete as a heading); the corpus's own secondary candidate 'Κεντρικό API' is a grammatical, semantically sound rendering of 'Core API'.",
  "adversarial_counter": "Βασικό API",
  "adversarial_rationale": "Κεντρικό means 'central/main' and drifts from the sense of 'core' as fundamental/essential; Greek technical documentation standardly renders 'Core' as Βασικό (or via πυρήνας/kernel), so Βασικό API is the more idiomatic choice."
}
```

## el / heading.name
```json
{
  "locale": "el",
  "id": "heading.name",
  "review_value": "Ονομασία",
  "review_rationale": "Both 'Ονομασία' and 'Όνομα' are acceptable, correct Greek words for 'Name'; with no clear correctness difference this is a genuine tie broken by the strong corpus majority.",
  "adversarial_counter": "Όνομα",
  "adversarial_rationale": "Ονομασία is a formal 'designation/appellation' register (used for product/species naming), not the natural word for a simple identifier column; Greek software localization standardly uses Όνομα for a 'Name' field/column, and here the proposal simply follows the corpus-dominant but non-standard form."
}
```

## es / phrase.class_provides_methods
```json
{
  "locale": "es",
  "id": "phrase.class_provides_methods",
  "review_value": "Esta clase proporciona {n} métodos para trabajar con objetos {api} objects en programas {platform}.",
  "review_rationale": "PLACEHOLDER_ERROR_DO_NOT_USE",
  "adversarial_counter": "Esta clase proporciona {n} métodos para trabajar con objetos {api} en programas {platform}.",
  "adversarial_rationale": "The proposed value contains a duplication bug -- 'objetos {api} objects' leaves the English word 'objects' untranslated and repeated right after its Spanish equivalent, whereas the corpus's actual dominant, correct form (212 occurrences) omits the stray English word entirely."
}
```

## fa / heading.see_also
```json
{
  "locale": "fa",
  "id": "heading.see_also",
  "review_value": "همچنین ببینید:",
  "review_rationale": "Idiomatic, standard Persian phrase for a 'See Also' cross-reference section; matches strong corpus majority.",
  "adversarial_counter": "همچنین ببینید",
  "adversarial_rationale": "The proposal matches the corpus-dominant form which appends a trailing colon; 'See Also' has no colon in English and no sibling heading in this set (Overview, Properties, Methods, etc.) carries one, so the colon is a corpus artifact, not correct style."
}
```

## fa / heading.methods
```json
{
  "locale": "fa",
  "id": "heading.methods",
  "review_value": "روش ها",
  "review_rationale": "Standard native-Persian plural for 'Methods' in technical documentation; matches strong corpus majority.",
  "adversarial_counter": "روش‌ها",
  "adversarial_rationale": "The root word روش is fine, but the plural suffix ها must attach via ZWNJ (نیم‌فاصله) after a joining letter like ش; 'روش ها' with a full space is a common but orthographically incorrect rendering, and the corpus itself attests 'روش‌ها' as the correctly-spaced minority variant."
}
```

## fa / heading.description
```json
{
  "locale": "fa",
  "id": "heading.description",
  "review_value": "توصیف",
  "review_rationale": "Acceptable, standard heading term for a descriptive-prose section; matches corpus plurality and previously reviewed value.",
  "adversarial_counter": "توضیحات",
  "adversarial_rationale": "توصیف carries a literary 'depiction/characterization' sense (describing a scene or person), whereas established Persian software-documentation convention (Microsoft/major vendor Persian terminology) uses توضیحات for a neutral 'Description' field or column heading."
}
```

## fa / heading.enumerations
```json
{
  "locale": "fa",
  "id": "heading.enumerations",
  "review_value": "شمارش ها",
  "review_rationale": "Standard CS term for enumerated types (cf. Persian Wikipedia 'نوع شمارشی'); corpus evidence is sparse and noisy (top candidate 'تبدیل و فضایی' = 'Transform and Spatial', an unrelated/misaligned string).",
  "adversarial_counter": "شمارش‌ها",
  "adversarial_rationale": "Same ZWNJ defect as Methods: شمارش ends in the joining letter ش, so the plural suffix needs a half-space (شمارش‌ها); a bare space is non-standard Persian typography."
}
```

## fa / heading.interfaces
```json
{
  "locale": "fa",
  "id": "heading.interfaces",
  "review_value": "رابط ها",
  "review_rationale": "Standard Persian technical term (plural of رابط) for programming interfaces; corpus top candidate 'هندسه و مش' ('Geometry and Mesh') is an unrelated/misaligned string from n=3 noisy sample.",
  "adversarial_counter": "رابط‌ها",
  "adversarial_rationale": "رابط ends in the joining letter ط, so its plural needs a ZWNJ (رابط‌ها); the proposed plain-space form 'رابط ها' is the same systemic spacing defect as Methods/Enumerations."
}
```

## fa / heading.structs
```json
{
  "locale": "fa",
  "id": "heading.structs",
  "review_value": "ساختار ها",
  "review_rationale": "Standard Persian plural for 'struct' type category, consistent with phrase.is_a_struct_in's 'ساختار'; single corpus sample ('اشیاء اولیه داخلی') is unreliable and not a faithful translation.",
  "adversarial_counter": "ساختارها",
  "adversarial_rationale": "ساختار ends in the non-joining letter ر, so its plural is conventionally written solid with no space or ZWNJ at all (ساختارها); the proposed 'ساختار ها' with a literal space is non-standard."
}
```

## fa / heading.classes
```json
{
  "locale": "fa",
  "id": "heading.classes",
  "review_value": "کلاس ها",
  "review_rationale": "Standard Persian loanword plural for 'Classes'; happens to match the (weak, 3-way-tied) corpus top candidate.",
  "adversarial_counter": "کلاس‌ها",
  "adversarial_rationale": "کلاس ends in the joining letter س, so correct orthography requires a ZWNJ before the plural suffix (کلاس‌ها); the proposed full-space 'کلاس ها' is the same recurring spacing defect."
}
```

## fa / table.header.description
```json
{
  "locale": "fa",
  "id": "table.header.description",
  "review_value": "توصیف",
  "review_rationale": "Matches the already-reviewed heading.description translation for internal consistency; source 'Description' has no colon so the colon-bearing corpus top candidate is rejected on fidelity grounds.",
  "adversarial_counter": "توضیحات",
  "adversarial_rationale": "Same issue as heading.description: توصیف is a depiction/characterization term, while توضیحات is the standard Persian term for a documentation 'Description' column."
}
```

## fi / heading.enumerations
```json
{
  "locale": "fi",
  "id": "heading.enumerations",
  "review_value": "Luettelot",
  "review_rationale": "Correct nominative plural heading using the 'luettelo' (enumeration/list) root used elsewhere in this corpus for 'enum'; the thin corpus top is the wrong partitive case, invalid as a stand-alone heading.",
  "adversarial_counter": "Luettelotyypit",
  "adversarial_rationale": "\"Luettelot\" means plain \"Lists,\" losing the enum-type sense; the same proposal batch itself renders \"enum\" as \"luettelotyyppi\" elsewhere, so the heading should parallel that as an enum-type noun rather than a bare list."
}
```

## fi / table.header.enumeration
```json
{
  "locale": "fi",
  "id": "table.header.enumeration",
  "review_value": "Luettelo",
  "review_rationale": "Corpus rows are stray class-name noise; singular form consistent with the heading.enumerations decision.",
  "adversarial_counter": "Luettelotyyppi",
  "adversarial_rationale": "\"Luettelo\" means \"List,\" not the CS-specific \"enumeration type\"; for consistency with the same batch's own \"luettelotyyppi\" usage for enum, this table header should carry the same type-specific noun."
}
```

## he / heading.core_api
```json
{
  "locale": "he",
  "id": "heading.core_api",
  "review_value": "API ליבה",
  "review_rationale": "Corpus-dominant 'אש גרעינית' ('nuclear fire') is a nonsensical MT error; 'ליבה' is the standard Hebrew word for 'core' in technical contexts.",
  "adversarial_counter": "ליבת API",
  "adversarial_rationale": "\"API ליבה\" inverts Hebrew's construct-state (smichut) word order -- it should be \"ליבת API\" (\"core-of API\") -- so although it rightly avoids the corpus's absurd unanimous \"אש גרעינית\" (\"nuclear fire\"), its own grammar is non-standard."
}
```

## hu / heading.methods
```json
{
  "locale": "hu",
  "id": "heading.methods",
  "review_value": "Módszerek",
  "review_rationale": "Standard Hungarian technical term for 'Methods'; matches dominant corpus form.",
  "adversarial_counter": "Metódusok",
  "adversarial_rationale": "In this class/API-reference context 'Methods' denotes OOP class methods, which Hungarian technical documentation calls 'metódusok'; 'módszerek' means general techniques/procedures and is a wrong-sense trap analogous to the confirmed es/de 'Methods' traps in this corpus, reinforced by the corpus's own phrase templates (e.g. class_provides_methods) preferring 'metódust'."
}
```

## hu / heading.accessor_methods
```json
{
  "locale": "hu",
  "id": "heading.accessor_methods",
  "review_value": "Hozzáférési módszerek",
  "review_rationale": "100% corpus consensus mistranslates 'accessor' as 'csatlakozó' (connector/plug); standard term uses 'hozzáférés' (access), consistent with this locale's table.header.access = 'Hozzáférés'.",
  "adversarial_counter": "Hozzáférési metódusok",
  "adversarial_rationale": "The 'hozzáférési' (access-related) correction over the corpus-dominant wrong 'csatlakozó' (connector) is right, but 'módszerek' should still be 'metódusok' for the same OOP-terminology reason as heading.methods."
}
```

## hu / phrase.is_a_class_in
```json
{
  "locale": "hu",
  "id": "phrase.is_a_class_in",
  "review_value": "{api} egy osztály az Aspose.{family} FOSS-ban {platform} számára.",
  "review_rationale": "Corpus is highly fragmented (top share only 16%); adopted the corpus's own best-structured variant, which avoids attaching a vowel-harmony-dependent case suffix directly onto the {platform} placeholder, but corrected 'a Aspose' to the grammatically required 'az Aspose' (vowel-initial word).",
  "adversarial_counter": "{api} egy osztály az Aspose.{family} FOSS for {platform} csomagban.",
  "adversarial_rationale": "'Aspose.{family} FOSS for {platform}' is a single fixed product name and should stay intact; the proposed value splits it by declining 'FOSS-ban' separately and re-attaching '{platform} számára', which distorts the product name and contradicts the correctly-intact pattern used by the sibling phrase.members_accessible_after_install in this same batch."
}
```

## hu / phrase.is_an_enum_in
```json
{
  "locale": "hu",
  "id": "phrase.is_an_enum_in",
  "review_value": "{api} egy enum az Aspose.{family} FOSS-ban {platform} számára.",
  "review_rationale": "Majority form wrongly uses the definite article 'az enum' ('the enum') instead of the indefinite 'egy enum' matching English 'a enum'; also corrected 'a Aspose'->'az Aspose', for consistency with the parallel is_a_class_in construction.",
  "adversarial_counter": "{api} egy enum az Aspose.{family} FOSS for {platform} csomagban.",
  "adversarial_rationale": "Same product-name-splitting defect as phrase.is_a_class_in ('FOSS-ban ... {platform} számára' breaks the fixed 'FOSS for {platform}' name)."
}
```

## hu / phrase.is_an_interface_in
```json
{
  "locale": "hu",
  "id": "phrase.is_an_interface_in",
  "review_value": "{api} egy interfész az Aspose.{family} FOSS-ban {platform} számára.",
  "review_rationale": "Corrected the article 'a'->'az' before vowel-initial 'Aspose' and the vowel-harmony suffix '-ben'->'-ban' to match the back-vowel word 'FOSS', for consistency with the parallel class/enum constructions.",
  "adversarial_counter": "{api} egy interfész az Aspose.{family} FOSS for {platform} csomagban.",
  "adversarial_rationale": "Same product-name-splitting defect; notably a minority corpus variant ('a Aspose.{family} FOSS for {platform}-ben') already shows the intact-name form is attainable and preferable."
}
```

## id / heading.values
```json
{
  "locale": "id",
  "id": "heading.values",
  "review_value": "Nilai-nilai",
  "review_rationale": "Semantically correct and strongly corpus-supported plural heading form for 'Values'.",
  "adversarial_counter": "Nilai",
  "adversarial_rationale": "Technical-heading convention in this same set drops plural reduplication (Properti, Kelas, Antarmuka, Enumerasi, Konstruktor all singular), and the corpus's own phrase.enum_defines_values proposal uses singular 'nilai' -- 'Nilai-nilai' (matching the 71%-share corpus form) is an inconsistent reduplicated plural not used for section headings."
}
```

## id / table.header.signature
```json
{
  "locale": "id",
  "id": "table.header.signature",
  "review_value": "Tanda tangan",
  "review_rationale": "Standard Indonesian technical rendering of API/method 'Signature', strong corpus majority.",
  "adversarial_counter": "Signature",
  "adversarial_rationale": "'Tanda tangan' means a person's handwritten/autograph signature, not a method/function signature -- this is a wrong-sense homograph error matching the corpus-dominant form (92% share), the same trap pattern as the ES/EL Overview cases; Indonesian technical docs conventionally keep 'Signature' untranslated for method signatures."
}
```

## ja / heading.see_also
```json
{
  "locale": "ja",
  "id": "heading.see_also",
  "review_value": "参照",
  "review_rationale": "Top candidate 参照する is a bare dictionary-form verb ('to reference'), grammatically wrong for a noun-phrase section heading; the noun form 参照 (2nd place, 33.7%) is the standard heading translation and matches prior review.",
  "adversarial_counter": "関連項目",
  "adversarial_rationale": "参照 (bare 'reference/citation') is not the established documentation convention for the cross-reference heading; Microsoft Docs and Oracle Javadoc both render 'See Also' as 関連項目, which appears in this corpus's own candidate list (rare, but present) while the corpus-dominant 参照する is a verb form unsuitable for a heading at all -- 関連項目 is the correct idiomatic choice."
}
```

## ja / phrase.enum_defines_values
```json
{
  "locale": "ja",
  "id": "phrase.enum_defines_values",
  "review_value": "この列挙は{n}つの値を定義します:",
  "review_rationale": "Dominant, grammatically correct template with proper counter usage; {n} placeholder preserved verbatim.",
  "adversarial_counter": "この列挙型は{n}つの値を定義します:",
  "adversarial_rationale": "Bare 列挙 reads as the action-noun 'enumerating/listing' rather than the enum-type itself, and is inconsistent with this corpus's own correct terminology for 'enum' (列挙型) used in heading.enumerations, table.header.enumeration, and phrase.is_an_enum_in -- 列挙型 should be used here for both precision and cross-corpus terminological consistency."
}
```

## ko / phrase.is_a_class_in
```json
{
  "locale": "ko",
  "id": "phrase.is_a_class_in",
  "review_value": "{api} {platform}에 대한 Aspose.{family} FOSS의 클래스입니다.",
  "review_rationale": "Top corpus candidate, preserves all three placeholders exactly and avoids the topic-particle (은/는) agreement bug that a dynamic {api} value would create.",
  "adversarial_counter": "{api}은(는) {platform}용 Aspose.{family} FOSS의 클래스입니다.",
  "adversarial_rationale": "This proposal reproduces the raw corpus-majority template (105/count) verbatim, which mistranslates 'for {platform}' as '{platform}에 대한' (meaning 'about/regarding {platform}', i.e. a class that discusses the platform, not one built for it) and drops the topic particle after {api}; the corpus's own second-place variant using '{platform}용' plus an explicit particle (은, 55/count) is both grammatically complete and semantically correct."
}
```

## lt / heading.name
```json
{
  "locale": "lt",
  "id": "heading.name",
  "review_value": "Vardas",
  "review_rationale": "'Vardas' is the established Lithuanian convention for a 'Name' column header in software UIs/docs (e.g. Windows Explorer file listings), and matches strong corpus majority in this exact corpus.",
  "adversarial_counter": "Pavadinimas",
  "adversarial_rationale": "\"Vardas\" denotes a person's given name in Lithuanian; for a table column listing names of API members/parameters/objects, the correct convention is \"Pavadinimas\", which is also present in the corpus as a real minority form (124/1624, 7.6%) alongside the dominant but non-standard \"Vardas\" (1231, 75.8%)."
}
```

## lt / phrase.is_a_class_in
```json
{
  "locale": "lt",
  "id": "phrase.is_a_class_in",
  "review_value": "{api} yra klasė Aspose.{family} FOSS {platform}.",
  "review_rationale": "Noun-first word order ('yra klasė ...') matches the dominant, grammatically natural pattern used consistently by this corpus's sibling interface/struct templates (both are real majorities with this exact order), so it is chosen over the class template's own narrow plurality alternate word-order; all three placeholders {api}/{family}/{platform} preserved verbatim.",
  "adversarial_counter": "{api} yra klasė Aspose.{family} FOSS, skirta {platform}.",
  "adversarial_rationale": "The proposed sentence drops any translation of \"for\", leaving \"FOSS {platform}\" as an ungrammatical noun-stack with no case/preposition marking the platform relationship; other corpus variants for the sibling templates do mark it (e.g. \"už {platform}\", \"{platform} platformai\"), confirming a connector such as \"skirta\" is required for grammatical completeness."
}
```

## lt / phrase.is_an_enum_in
```json
{
  "locale": "lt",
  "id": "phrase.is_an_enum_in",
  "review_value": "{api} yra išvardijimas Aspose.{family} FOSS {platform}.",
  "review_rationale": "Uses the standard Lithuanian programming term 'išvardijimas' for enum (consistent with heading.enumerations) rather than the corpus's untranslated 'enum'/'enumas' loanword forms, while matching the noun-first sentence structure shared by the class/interface/struct sibling templates; all placeholders preserved verbatim.",
  "adversarial_counter": "{api} yra išvardijimas Aspose.{family} FOSS, skirtas {platform}.",
  "adversarial_rationale": "Same defect as the class/interface templates: omitting a rendering of \"for\" (contrast the corpus's own \"{platform} platformai\" dative-marked variant, 40% share) leaves the Lithuanian sentence incomplete/ungrammatical."
}
```

## lt / phrase.is_an_interface_in
```json
{
  "locale": "lt",
  "id": "phrase.is_an_interface_in",
  "review_value": "{api} yra sąsaja Aspose.{family} FOSS {platform}.",
  "review_rationale": "'Sąsaja' is the standard Lithuanian term for interface and this is the clear corpus majority structure; all placeholders preserved verbatim.",
  "adversarial_counter": "{api} yra sąsaja Aspose.{family} FOSS, skirta {platform}.",
  "adversarial_rationale": "Identical missing-preposition defect; the corpus itself shows a real competing variant that supplies \"už {platform}\" (23% share) confirming the \"for\" relationship must be marked, which the proposed value fails to do."
}
```

## lv / phrase.is_a_class_in
```json
{
  "locale": "lv",
  "id": "phrase.is_a_class_in",
  "review_value": "{api} ir klase Aspose.{family} FOSS for {platform}.",
  "review_rationale": "Corpus majority translates 'for' as the colloquial preposition 'priekš', but the 'Aspose.X FOSS for Y' string is a fixed Aspose product/brand name that should stay untranslated (confirmed by this corpus's own 92%-majority handling of the identical product-name clause in members_accessible_after_install); all placeholders preserved.",
  "adversarial_counter": "{api} ir klase Aspose.{family} FOSS priekš {platform}.",
  "adversarial_rationale": "Corpus evidence shows the properly-translated dominant form uses \"priekš\" for \"for\" (112 hits); the proposed value instead reproduces the minority, incompletely-translated variant that leaves English \"for\" untranslated (47 hits) -- a genuine defect, not the correct target rendering."
}
```

## lv / phrase.is_an_enum_in
```json
{
  "locale": "lv",
  "id": "phrase.is_an_enum_in",
  "review_value": "{api} ir enum Aspose.{family} FOSS for {platform}.",
  "review_rationale": "Same brand-name-integrity reasoning as is_a_class_in: keep 'Aspose.X FOSS for Y' untranslated rather than the corpus-majority colloquial 'priekš'; all placeholders preserved.",
  "adversarial_counter": "{api} ir enum Aspose.{family} FOSS priekš {platform}.",
  "adversarial_rationale": "Same defect as is_a_class_in: the corpus-correct dominant form translates \"for\" as \"priekš\" (55 hits) while the proposed value matches the minority untranslated \"for\" variant (8 hits)."
}
```

## nl / table.header.signature
```json
{
  "locale": "nl",
  "id": "table.header.signature",
  "review_value": "Handtekening",
  "review_rationale": "Dominant, clean corpus consensus (90.4%) and the standard Dutch term for Signature.",
  "adversarial_counter": "Signatuur",
  "adversarial_rationale": "\"Handtekening\" means a personal/autograph signature, but in a method-overload table \"Signature\" refers to a method's type signature -- the correct Dutch technical term is \"Signatuur\"; this is a false-friend literal translation that happens to be corpus-dominant (90.4% share per table_headers.json), matching the exact known-trap pattern of high vote share masking a wrong-sense translation."
}
```

## no / heading.enumerations
```json
{
  "locale": "no",
  "id": "heading.enumerations",
  "review_value": "Oppramsinger",
  "review_rationale": "No usable corpus signal (n=11, top candidate is a product name); chosen for internal corpus consistency with the strongly-attested phrase.enum_defines_values wording ('oppramsingen', 98% consensus) rather than the less-attested loanword 'Enumerasjoner'.",
  "adversarial_counter": "Oppregninger",
  "adversarial_rationale": "\"Oppramsinger\" means a casual/rambling recitation of items (negative connotation, e.g. \"en endeløs oppramsing\"), not the CS enum-type sense; the correct native term, structurally parallel to the confirmed-correct German \"Aufzählung\" (auf+zählen = opp+regne), is \"Oppregning(er)\"."
}
```

## no / table.header.enumeration
```json
{
  "locale": "no",
  "id": "table.header.enumeration",
  "review_value": "Oppramsing",
  "review_rationale": "Corpus candidates are noise (product/type names, not translations); chosen as the singular form of the enumerations heading choice for internal corpus consistency.",
  "adversarial_counter": "Oppregning",
  "adversarial_rationale": "Same sense-error as heading.enumerations: \"Oppramsing\" implies an informal rattling-off, not the technical enum-type meaning; \"Oppregning\" is the correct native Norwegian equivalent (paralleling German's correct \"Aufzählung\")."
}
```

## ro / heading.description
```json
{
  "locale": "ro",
  "id": "heading.description",
  "review_value": "Descriere:",
  "review_rationale": "Inline field-label use (Javadoc-style 'Description:' before body text, distinct from the table-column role); corpus's colon-bearing form is the plurality candidate for this specifically inline-labeled section-heading role.",
  "adversarial_counter": "Descriere",
  "adversarial_rationale": "As a standalone section_heading (sibling to Overview/Properties/Methods/Values, none of which carry a trailing colon), 'Descriere' without colon is the internally-consistent form; the trailing colon in 'Descriere:' appears to be bleed-through from a separate, much stronger corpus pattern (table_headers.json cell context at 97% share) where 'Description:' functions as an inline field label followed by content on the same line -- a different grammatical role than a full section heading, and in the section-heading dataset itself the colon form's support is weak and noisy (56% share, second place is the unrelated word 'Proprietăți')."
}
```

## ru / table.header.signature
```json
{
  "locale": "ru",
  "id": "table.header.signature",
  "review_value": "Подпись",
  "review_rationale": "Standard Russian term used for API method signatures, strongly corpus-dominant.",
  "adversarial_counter": "Сигнатура",
  "adversarial_rationale": "Both the proposal and the 96.9%-dominant corpus form use \"Подпись\" (handwritten/autograph signature), but standard Russian programming documentation renders \"method/function signature\" with the loanword \"сигнатура\" (e.g. \"сигнатура метода\"), so this looks like the same generic-dictionary mistranslation pattern seen in the confirmed Access/Property/Value/Returns traps in this corpus."
}
```

## sr / heading.returns
```json
{
  "locale": "sr",
  "id": "heading.returns",
  "review_value": "Vraća",
  "review_rationale": "Standard concise verb-form heading used in Serbian API docs for a 'Returns' section/column ('Vraća:' = 'Returns:'); present in the corpus itself as a minority variant, while the dominant candidate is the more awkward gerund 'Vraćanje/Враћање' (literally 'the returning').",
  "adversarial_counter": "Vraćanje",
  "adversarial_rationale": "As a table column header running parallel to noun headers like \"Metod\"/\"Opis\", the bare verb form \"Vraća\" is grammatically incongruous; the sr corpus strongly favors the nominalized \"Vraćanje\" (94.6% share, 53 vs 3), which reads correctly as a header alongside \"Metod ... Opis\"."
}
```

## sv / phrase.class_provides_methods
```json
{
  "locale": "sv",
  "id": "phrase.class_provides_methods",
  "review_value": "Denna klass ger {n} metoder för att arbeta med {api} objekt i {platform}-program.",
  "review_rationale": "This exact clause recurs consistently as the clean opening of both sampled corpus templates; the reported 'top' full-string candidates are contaminated with appended per-example method-list/install text that belongs to other content, so the isolated share of the literal top string is not representative.",
  "adversarial_counter": "Denna klass ger {n} metoder för att arbeta med {api}-objekt i {platform}-program.",
  "adversarial_rationale": "'{api} objekt' is unhyphenated särskrivning of a foreign-identifier + noun compound; Swedish requires 'X-objekt' (as the same sentence correctly does with '{platform}-program'), so a hyphen must be inserted even though the whole corpus consistently omits it."
}
```

## th / heading.enumerations
```json
{
  "locale": "th",
  "id": "heading.enumerations",
  "review_value": "การนับจำนวน",
  "review_rationale": "Corpus-dominant 'การนับทะเบียน' wrongly reads as 'registry/registration counting', unrelated to programming enumerations; 'การนับจำนวน' is corroborated by this same corpus's clean, high-share phrase.enum_defines_values translation which refers to 'this enumeration' as 'การนับจำนวนนี้'.",
  "adversarial_counter": "การแจงนับ",
  "adversarial_rationale": "\"การนับจำนวน\" literally means \"counting a quantity/number\" and conflates the generic sense of \"enumerate\" (tally) with the CS sense of \"a listed set of named constants\"; the correct Thai technical term for enumerated types is \"การแจงนับ\"/\"การแจกแจง\", and the corpus data for this exact heading is itself unstable (58% share on only 17 samples, competing with the equally wrong \"การนับทะเบียน\")."
}
```

## th / table.header.enumeration
```json
{
  "locale": "th",
  "id": "table.header.enumeration",
  "review_value": "การนับจำนวน",
  "review_rationale": "Corpus rows are confirmed ASCII-vote-in-non-Latin-locale contamination (a class name 'ReferenceMode' and other untranslated English words), not real translations; aligned with the vocabulary confirmed via phrase.enum_defines_values.",
  "adversarial_counter": "การแจงนับ",
  "adversarial_rationale": "Same issue as heading.enumerations: \"การนับจำนวน\" misrepresents \"Enumeration\" as mere quantity-counting rather than a listed set of named constants; the raw corpus data for this exact singular table header is itself degenerate (n=9, dominant candidate is the garbage token \"ReferenceMode\"), so it provides no support for the proposed value."
}
```

## tr / phrase.enum_defines_values
```json
{
  "locale": "tr",
  "id": "phrase.enum_defines_values",
  "review_value": "Bu sıralama {n} değer tanımlar:",
  "review_rationale": "Direct, grammatical translation of 'This enumeration defines {n} values:' consistent with the 'Numaralandırma/sıralama' terminology chosen for enum headings; placeholder {n} preserved verbatim; corpus's genuine top variant ('Bu sayım {n} değer tanımlar:') reuses the false-friend 'sayım' (count/tally) rejected elsewhere for 'enumeration'.",
  "adversarial_counter": "Bu numaralandırma {n} değer tanımlar:",
  "adversarial_rationale": "\"Sıralama\" means ordering/sequencing/ranking, not \"enumeration\" in the type-listing sense, and is inconsistent with the correctly chosen \"Numaralandırmalar\" for the Enumerations heading; it is also unattested anywhere in the corpus (which instead uses \"liste\" or the equally flawed \"sayım\"), so \"numaralandırma\" is the more accurate and internally consistent term."
}
```

## uk / phrase.inherits_from
```json
{
  "locale": "uk",
  "id": "phrase.inherits_from",
  "review_value": "Наслідує від: {api}.",
  "review_rationale": "Only clean (non-corrupted) corpus candidate and it is the grammatically correct standard rendering; all other candidates are extraction-corrupted concatenations of unrelated text.",
  "adversarial_counter": "Успадковує від: {api}.",
  "adversarial_rationale": "\"Наслідувати\" means 'to imitate/follow an example' in Ukrainian, not 'to inherit' in the OOP sense; the canonical CS term (cf. Ukrainian Wikipedia 'Успадкування (програмування)') is 'успадковувати', so 'Наслідує від' is a false-cognate calque (likely from Russian 'наследовать') despite being corpus-dominant."
}
```

## uk / phrase.class_provides_methods
```json
{
  "locale": "uk",
  "id": "phrase.class_provides_methods",
  "review_value": "Цей клас надає {n} методи для роботи з об'єктами {api} в програмах {platform}.",
  "review_rationale": "The 1116 corpus samples are almost entirely extraction-corrupted (concatenated with unrelated trailing text, top share <1%); reconstructed the clean recurring opening sentence fragment shared across many corrupted samples as the standard rendering, preserving all three placeholders.",
  "adversarial_counter": "Цей клас надає {n} методів для роботи з об'єктами {api} в програмах {platform}.",
  "adversarial_rationale": "Ukrainian numeral-noun agreement requires 'метод' (n=1), 'методи' (n=2-4), or 'методів' (n=0,5+); hard-coding 'методи' is only correct for a narrow numeric range and reads as ungrammatical for the majority of real method counts (e.g. 'надає 10 методи' is wrong), so genitive plural 'методів' is the safer general-purpose default."
}
```

## uk / phrase.enum_defines_values
```json
{
  "locale": "uk",
  "id": "phrase.enum_defines_values",
  "review_value": "Це перерахування визначає {n} значення:",
  "review_rationale": "Near-even split between 'значення' (nominative/accusative plural, correct for n=2-4) and 'значень' (genitive plural, correct for other n) reflects natural per-instance number agreement rather than template noise; picked the very slight corpus majority as the fixed default since both forms are grammatically acceptable for an unspecified count.",
  "adversarial_counter": "Це перерахування визначає {n} значень:",
  "adversarial_rationale": "The same numeral-agreement rule applies here: 'значення' is only correct for n=1-4, while n≥5 (very common for enumerations) requires the genitive plural 'значень', and the corpus itself is split almost evenly (274 vs 249) between the two forms, confirming this is a real, unresolved agreement issue rather than a stylistic quirk."
}
```

## vi / heading.enumerations
```json
{
  "locale": "vi",
  "id": "heading.enumerations",
  "review_value": "Enum",
  "review_rationale": "This corpus consistently keeps 'enum' as an English loanword elsewhere (98% share in phrase.is_an_enum_in), so the bare heading follows that established convention rather than the tiny (n=8) noisy sample specific to this heading.",
  "adversarial_counter": "Kiểu liệt kê",
  "adversarial_rationale": "Bare \"Enum\" is an under-localized loanword; standard Vietnamese technical convention (cf. Vietnamese CS references/Wikipedia \"kiểu liệt kê\") translates \"enumeration\" fully, and doing so keeps this heading consistent with sibling headings that ARE fully translated (Classes→Lớp, Structs→Cấu trúc, Interfaces→Giao diện)."
}
```

## vi / table.header.enumeration
```json
{
  "locale": "vi",
  "id": "table.header.enumeration",
  "review_value": "Enum",
  "review_rationale": "Kept as the same English loanword used elsewhere for 'enum' (98% share in phrase.is_an_enum_in) for cross-entry consistency; corpus has no real Vietnamese candidate for this column.",
  "adversarial_counter": "Kiểu liệt kê",
  "adversarial_rationale": "Same under-localization issue as heading.enumerations: bare \"Enum\" is inconsistent with fully-translated sibling column headers (Class→Lớp, Method→Phương thức, Property→Thuộc tính); the standard Vietnamese term should be used instead."
}
```

## vi / phrase.enum_defines_values
```json
{
  "locale": "vi",
  "id": "phrase.enum_defines_values",
  "review_value": "Enum này xác định {n} giá trị:",
  "review_rationale": "The 100%-share corpus form mistranslates 'enumeration' (back-referencing the enum type just introduced) as generic 'danh sách' (list) -- a confirmed-wrong overwhelming-majority pattern; corrected using the 'enum' loanword already established elsewhere in this corpus, {n} token preserved.",
  "adversarial_counter": "Kiểu liệt kê này xác định {n} giá trị:",
  "adversarial_rationale": "Same \"Enum\" under-localization issue as the Enumeration headings; \"this enumeration\" should use the standard Vietnamese term rather than the bare loanword, for both correctness and internal consistency."
}
```