# GitLab Translation Projects — Eliminated Projects

15 projects eliminated after README + source code inspection via GitLab API.

## Elimination Criteria
- **Code translator only:** Translates programming languages, not natural language content.
- **XML translator only:** Translates XML resource files, not Markdown.
- **RESX translator only:** Translates .resx/.json resource files, not Markdown.
- **JSON translator only:** Translates JSON resource files, not Markdown.
- **Empty/unusable:** Template README only, no implementation.
- **Not translation-related:** Project does not perform translation.
- **Prompt research only:** Uses .md as test input but is not a translation tool.

## Eliminated Projects

| ID | Name | Path | Category | Evidence | Confidence |
|----|------|------|----------|----------|------------|
| 3 | Landing Page Translator | chernihiv-groupdocs-com/groupdocs-products/ai-translator-for-products-generator | JSON translator only | README: translates JSON resource files (`templates/data/index/en.json`). Source: `scripts/` contains JSON processing. No .md handling found. | High |
| 51 | Blog post generator and translater AI Agent | almaty/blog-post-generator-and-translater-ai-agent | Empty/unusable | README: NestJS boilerplate template. Source: `src/` contains NestJS scaffolding with cron service stubs. No translation logic found in source. `package.json` has only NestJS deps. | High |
| 88 | Resource Translator Agent | bryansk-pdf/web/resource-translator-agent | RESX translator only | README: VS Code extension for `.resx` files. Source: `src/` contains resx XML parsing + LLM translation. `.vscodeignore`, `vsc-extension-quickstart.md` confirm VSCode extension. No .md handling. | High |
| 97 | Translation Checker Agent | rostov/rostov-groupdocs-app/translation-checker-agent | Empty/unusable | Only file is `README.md` with GitLab default template content. No source code, no implementation. | High |
| 144 | TestcasesTranslationAgent | gulou-cells/xinyazhu/testcasestranslationagent | Code translator only | README: translates C# test case source files. Source: `TranslateAgent/` contains C# code that reads `.cs` files from Aspose.Cells examples and translates code comments/strings. | High |
| 166 | GridJsLocaleGenerator | gulou-cells/peterzhou/gridjslocalegenerator | JSON translator only | README: generates JS locale files for GridJs UI. Source: `LocaleToolConsoleApp/` processes `en.js` → target language `.js` files (JSON-like objects). No .md handling. | High |
| 182 | Resx-Localiser | rostov/krakow-groupdocs-ai/resx-localiser | RESX translator only | README: automated RESX localization agent. Source: `Resx.Localiser/` has C# code for `.resx` XML parsing, translation memory, branch sync. No .md handling. | High |
| 209 | CodeTranslator Attributes Generator Agent | bryansk-pdf/derived/cpp/codetranslator-attributes-generator-agent | Code translator only | README: scans C/C++ headers, generates attribute content. Source: `CodeTranslatorAttributesGeneratorAgent/` processes `.h` files via LLM. No natural language translation. | High |
| 313 | Java To Apex Translator Agent | uly-codeporting/java-to-apex-translator | Code translator only | README: translates Java source to Salesforce Apex. Source: `src/` contains Java→Apex conversion via LLM + Salesforce deployment. `pom.xml` confirms Java project. | High |
| 318 | XmlTranslationAgent | xuanwu-diagram/xml-translation-agent | XML translator only | README: translates XML resource files. Source: `Services/`, `Core/` parse XML key-value pairs, batch to LLM, output translated XML. `XmlTranslationAgent.csproj` confirms C# project. No .md handling. | High |
| 321 | Scan Missing and Translate Resx | sialkot/islamabad-fileformat/scan-missing-and-translate-resx | RESX translator only | README: scans .NET source for missing resource keys, translates `en.json` to target languages. Source: `src/` has C# code for resource file scanning. `TranslateResx.sln`, `Dockerfile` confirm .NET project. No .md handling. | High |
| 403 | TranslateAgent | xuanwu-diagram/translateagent | XML translator only | README: translates XML resource files (resources.xml). Source: `Services/`, `Models/` load XML, batch key-value pairs to LLM. `TranslateAgent.csproj` confirms C#. No .md handling. | High |
| 454 | Translation Prompt Optimizer | chernihiv-groupdocs-com/groupdocs-labs/translation-prompt-optimizer | Prompt research only | README: automated prompt optimization for LLM translation. Source: `run_experiment.py`, `prompt_config.py` run experiments on `source_post.md` measuring quality scores. Uses .md as test subject but is not a translation pipeline. | High |
| 626 | Dzen Agent Knowledge Hub | lviv-html/dzen-agent-knowledge-hub | Not translation-related | README: knowledge hub for agents, ingests posts, runs Qwen analysis, publishes via Quartz. Source: `dzen/`, `tools/`, `scripts/` do knowledge extraction and structuring. "Multilingual" in description refers to multilingual knowledge base output, not translation of .md files. | High |
| 698 | Localization Sync Agent | bryansk-pdf/derived/cloud/localization-sync-agent | JSON/YAML translator only | README: multi-agent translator+reviewer using LangGraph for localization files. Source: `backend/`, `frontend/` (FastAPI + React). Translates i18n locale files (likely JSON/YAML), not .md content. Default branch: `main`. | Medium |

## Uncertain Eliminations
- **ID 698 (Localization Sync Agent):** Classified as JSON/YAML translator at medium confidence. Could potentially handle .md if extended, but no .md processing was found in source inspection. Keeping as eliminated but noting uncertainty.

## Re-inclusion Candidates
None. All 15 projects were inspected via API (README + source tree + key files). No project showed evidence of .md translation capability.
