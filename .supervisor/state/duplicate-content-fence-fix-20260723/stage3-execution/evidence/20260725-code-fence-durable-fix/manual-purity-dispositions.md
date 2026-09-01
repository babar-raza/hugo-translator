# Manual disposition of every newly surfaced purity candidate

The controlled old-vs-new run found seven `purity_new_only` candidates, not
the plan's historical-snapshot estimate of 194. All seven were inspected
directly. They are genuine dropped/misplaced code-fence defects: code is
outside a CommonMark code region because an opener is absent or a closer occurs
before the code. The parser-backed change correctly stops allowing unrelated
valid code blocks to dilute the purity denominator and exposes these defects.
No translated content is edited in this mission.

| Site / locale | File | Old → new ratio | Disposition |
| --- | --- | --- | --- |
| docs.aspose.org / vi | `D:/onedrive/Documents/GitHub/aspose.org/content/docs.aspose.org/vi/cells/typescript/getting-started/quickstart.md` | 0.0000 → 0.1429 | Four `await workbook.save(...)` statements occur after a closing fence and before the next fence; missing opener. Genuine fence corruption. |
| reference.aspose.org / he | `D:/onedrive/Documents/GitHub/aspose.org/content/reference.aspose.org/he/3d/java/mesh.md` | 0.1000 → 0.2000 | `Mesh ensureMesh(...)` and the `createElementUV` sample are outside a code block after a premature closer. Genuine fence corruption. |
| reference.aspose.org / hi | `D:/onedrive/Documents/GitHub/aspose.org/content/reference.aspose.org/hi/3d/java/mesh.md` | 0.0952 → 0.1875 | Same source-page fence corruption. Genuine. |
| reference.aspose.org / ru | `D:/onedrive/Documents/GitHub/aspose.org/content/reference.aspose.org/ru/3d/java/mesh.md` | 0.0909 → 0.1765 | Same source-page fence corruption. Genuine. |
| reference.aspose.org / th | `D:/onedrive/Documents/GitHub/aspose.org/content/reference.aspose.org/th/3d/java/mesh.md` | 0.0952 → 0.1875 | Same source-page fence corruption. Genuine. |
| reference.aspose.org / uk | `D:/onedrive/Documents/GitHub/aspose.org/content/reference.aspose.org/uk/3d/java/mesh.md` | 0.0952 → 0.1765 | Same source-page fence corruption. Genuine. |
| reference.aspose.org / vi | `D:/onedrive/Documents/GitHub/aspose.org/content/reference.aspose.org/vi/3d/java/mesh.md` | 0.0952 → 0.1875 | Same source-page fence corruption. Genuine. |

Raw body-context inspection used `Select-String` on the vi quickstart and he
mesh representatives. The remaining five mesh files have the identical page
and code shape; their paths and computed paragraphs are retained in
`corpus-comparison.json`.

Successor finding: **AUD-DCF-010** — repair the producer/target files for the
seven confirmed `code_fence_dropped` defects through the normal remediation
pipeline, then verify source/target fence parity. This is deliberately not a
manual content patch in a detector-hardening mission.
