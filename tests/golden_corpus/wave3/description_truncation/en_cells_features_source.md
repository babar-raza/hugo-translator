---
page_role: howto_article
title: Features
description: 'Overview of all major capabilities in Aspose.Cells FOSS for .NET: workbook
  I/O, cell data, styling, conditional formatting, validation, auto-filter, hyperlinks,
  page setup, and worksheet management.'
weight: 10
type: docs
provenance:
  content_origin: skill-generated
  last_mechanism: manual-edit-skill
  reviewed: false
  content_created_at: '2026-04-07'
  auto_updatable: true
  content_hash: 431fa1e9702abbf02cb13bde2680ab0a
evidence:
  model_sha: 455b1c37a5a9321cf31e71d50d198da9e0dc8cc4
  model_version: 26.6.0.0
  claims:
  - CLM-cells-0ff38d
  - CLM-cells-160083
  - CLM-cells-3fca6b
  - CLM-cells-409d21
  - CLM-cells-9cbe22
  apis:
  - CellArea.CreateCellArea
  - Cells.Merge
  - FillPattern.Solid
  - FormatConditionType.CellValue
  - HorizontalAlignmentType.Center
  - OperatorType.Between
  - PageOrientationType.Landscape
  - PaperSizeType.PaperA4
  - ValidationType.Decimal
  - ValidationType.List
  - VisibilityType.Hidden
  - Workbook
  - Workbook.DefinedNames
  - Workbook.Save
  - Workbook.Worksheets
  formats:
  - ext: xlsx
    support: both
  sections:
  - heading: Features
    line: 138
    claims: []
    apis: []
    formats:
    - ext: xlsx
      support: both
  - heading: Workbook Create, Load, and Save
    line: 144
    claims:
    - CLM-cells-160083
    - CLM-cells-409d21
    apis:
    - Workbook
    - Workbook.Save
    - Workbook.Worksheets
    formats:
    - ext: xlsx
      support: both
  - heading: Cell Data and Formulas
    line: 171
    claims:
    - CLM-cells-160083
    - CLM-cells-409d21
    apis:
    - Workbook
    - Workbook.Save
    - Workbook.Worksheets
    formats:
    - ext: xlsx
      support: both
  - heading: Cell Styling
    line: 196
    claims:
    - CLM-cells-160083
    - CLM-cells-409d21
    apis:
    - FillPattern.Solid
    - HorizontalAlignmentType.Center
    - Workbook
    - Workbook.Save
    - Workbook.Worksheets
    formats:
    - ext: xlsx
      support: both
  - heading: Conditional Formatting
    line: 220
    claims:
    - CLM-cells-160083
    - CLM-cells-3fca6b
    - CLM-cells-409d21
    apis:
    - CellArea.CreateCellArea
    - FillPattern.Solid
    - FormatConditionType.CellValue
    - OperatorType.Between
    - Workbook
    - Workbook.Save
    - Workbook.Worksheets
    formats:
    - ext: xlsx
      support: both
  - heading: Data Validation
    line: 245
    claims:
    - CLM-cells-160083
    - CLM-cells-3fca6b
    - CLM-cells-409d21
    apis:
    - CellArea.CreateCellArea
    - OperatorType.Between
    - ValidationType.Decimal
    - ValidationType.List
    - Workbook
    - Workbook.Save
    - Workbook.Worksheets
    formats:
    - ext: xlsx
      support: both
  - heading: Auto-Filter
    line: 272
    claims:
    - CLM-cells-160083
    - CLM-cells-409d21
    apis:
    - Workbook
    - Workbook.Save
    - Workbook.Worksheets
    formats:
    - ext: xlsx
      support: both
  - heading: Hyperlinks and Defined Names
    line: 295
    claims:
    - CLM-cells-160083
    - CLM-cells-409d21
    - CLM-cells-9cbe22
    apis:
    - Workbook
    - Workbook.DefinedNames
    - Workbook.Save
    - Workbook.Worksheets
    formats:
    - ext: xlsx
      support: both
  - heading: Page Setup
    line: 316
    claims:
    - CLM-cells-160083
    - CLM-cells-409d21
    apis:
    - PageOrientationType.Landscape
    - PaperSizeType.PaperA4
    - Workbook
    - Workbook.Save
    - Workbook.Worksheets
    formats:
    - ext: xlsx
      support: both
  - heading: Worksheet Management
    line: 337
    claims:
    - CLM-cells-0ff38d
    - CLM-cells-160083
    - CLM-cells-409d21
    apis:
    - Cells.Merge
    - VisibilityType.Hidden
    - Workbook
    - Workbook.Save
    - Workbook.Worksheets
    formats:
    - ext: xlsx
      support: both
  - heading: Common Issues
    line: 371
    claims: []
    apis: []
    formats:
    - ext: xlsx
      support: both
  - heading: FAQ
    line: 382
    claims: []
    apis: []
    formats:
    - ext: xlsx
      support: both
grade: A
graded_content_hash: "431fa1e9702abbf02cb13bde2680ab0a"
grade_reasons:
  - "No findings -> grade A"
---

## Features

Aspose.Cells FOSS for .NET is a pure managed .NET library for creating, reading, and modifying Excel XLSX spreadsheets. The entry point is the `Workbook` class, which provides access to worksheets, defined names, and save/load operations. This page summarises every major feature area with brief code examples.

---

### Workbook Create, Load, and Save

Create a new workbook with `new Workbook()`. Load an existing XLSX file by passing a file path to the constructor. Use `LoadOptions` to enable fault-tolerant loading. Call `Workbook.Save(path)` to persist changes.

```csharp
using Aspose.Cells_FOSS;

// New workbook
var wb = new Workbook();
wb.Worksheets[0].Cells["A1"].PutValue("Hello");
wb.Save("output.xlsx");

// Load with repair options
var opts = new LoadOptions { TryRepairPackage = true, TryRepairXml = true };
try
{
    var loaded = new Workbook("input.xlsx", opts);
    Console.WriteLine(loaded.Worksheets[0].Cells["A1"].StringValue);
}
catch (WorkbookLoadException ex)
{
    Console.WriteLine("Load failed: " + ex.Message);
}
```

---

### Cell Data and Formulas

Use `Cell.PutValue()` to write strings, integers, decimals, booleans, and `DateTime` values. Set `Cell.Formula` to assign an Excel-compatible formula string. Read back display text via `Cell.StringValue` and the raw value via `Cell.Value`.

```csharp
using Aspose.Cells_FOSS;

var wb = new Workbook();
var ws = wb.Worksheets[0];

ws.Cells["A1"].PutValue("Qty");
ws.Cells["B1"].PutValue("Price");
ws.Cells["C1"].PutValue("Total");
ws.Cells["A2"].PutValue(10);
ws.Cells["B2"].PutValue(4.99m);
ws.Cells["C2"].Formula = "=A2*B2";

wb.Save("data.xlsx");

var loaded = new Workbook("data.xlsx");
Console.WriteLine(loaded.Worksheets[0].Cells["C2"].StringValue); // 49.9
```

---

### Cell Styling

Retrieve and modify the `Style` object for any cell with `Cell.GetStyle()` and `Cell.SetStyle()`. The `Style` class provides `Font` (bold, italic, size, name), `ForegroundColor`, `Pattern` (of type `FillPattern`), `HorizontalAlignment` (using `HorizontalAlignmentType`), and border control through `Borders`.

```csharp
using Aspose.Cells_FOSS;

var wb = new Workbook();
var cell = wb.Worksheets[0].Cells["A1"];
cell.PutValue("Styled Header");

var style = cell.GetStyle();
style.Font.Bold = true;
style.Font.Size = 14;
style.Pattern = FillPattern.Solid;
style.ForegroundColor = Color.FromArgb(255, 198, 239, 206);
style.HorizontalAlignment = HorizontalAlignmentType.Center;
cell.SetStyle(style);

wb.Save("styled.xlsx");
```

---

### Conditional Formatting

`Worksheet.ConditionalFormattings` returns a `ConditionalFormattingCollection`. Call `Add()` to create a rule set, then `AddCondition()` to add rules using `FormatConditionType` and `OperatorType`. Supported condition types include `CellValue`, `Expression`, `ColorScale`, `DataBar`, and `IconSet`.

```csharp
using Aspose.Cells_FOSS;

var wb = new Workbook();
var ws = wb.Worksheets[0];
for (var i = 0; i < 10; i++)
    ws.Cells[i, 0].PutValue(i + 1);

var ruleSet = ws.ConditionalFormattings[ws.ConditionalFormattings.Add()];
ruleSet.AddArea(CellArea.CreateCellArea("A1", "A10"));
var rule = ruleSet[ruleSet.AddCondition(FormatConditionType.CellValue, OperatorType.Between, "3", "7")];
var ruleStyle = rule.Style;
ruleStyle.Pattern = FillPattern.Solid;
ruleStyle.ForegroundColor = Color.FromArgb(255, 255, 199, 206);
rule.Style = ruleStyle;

wb.Save("cf.xlsx");
```

---

### Data Validation

`Worksheet.Validations` returns a `ValidationCollection`. Call `Add(CellArea)` to create a `Validation` for a cell range. Set the `Type` property using `ValidationType` (`List`, `Decimal`, or `Custom`). Configure `Formula1`, `Formula2`, `Operator`, `InputTitle`, `InputMessage`, `ErrorTitle`, and `ErrorMessage`.

```csharp
using Aspose.Cells_FOSS;

var wb = new Workbook();
var ws = wb.Worksheets[0];

var listVal = ws.Validations[ws.Validations.Add(CellArea.CreateCellArea("A1", "A10"))];
listVal.Type = ValidationType.List;
listVal.Formula1 = "\"Open,Closed,Pending\"";
listVal.InCellDropDown = true;

var numVal = ws.Validations[ws.Validations.Add(CellArea.CreateCellArea("B1", "B10"))];
numVal.Type = ValidationType.Decimal;
numVal.Operator = OperatorType.Between;
numVal.Formula1 = "0";
numVal.Formula2 = "100";
numVal.ShowError = true;

wb.Save("validation.xlsx");
```

---

### Auto-Filter

`Worksheet.AutoFilter` exposes the `AutoFilter` object. Set `AutoFilter.Range` to define the header row range. Access `AutoFilter.FilterColumns` (a collection) and call `Add(columnIndex)` to activate filtering on a specific column.

```csharp
using Aspose.Cells_FOSS;

var wb = new Workbook();
var ws = wb.Worksheets[0];

ws.Cells["A1"].PutValue("Name");
ws.Cells["B1"].PutValue("Region");
ws.Cells["C1"].PutValue("Sales");
ws.Cells["A2"].PutValue("Alice"); ws.Cells["B2"].PutValue("North"); ws.Cells["C2"].PutValue(1200);

ws.AutoFilter.Range = "A1:C1";
ws.AutoFilter.FilterColumns.Add(1);

wb.Save("filter.xlsx");
```

---

### Hyperlinks and Defined Names

`Worksheet.Hyperlinks` is a `HyperlinkCollection`. Call `Add()` to insert external URLs, internal cell references, or mailto links. Set `Hyperlink.TextToDisplay` and `Hyperlink.ScreenTip` for user-facing text. `Workbook.DefinedNames` is a `DefinedNameCollection`; call `Add(name, refersTo)` to create named ranges.

```csharp
using Aspose.Cells_FOSS;

var wb = new Workbook();
var ws = wb.Worksheets[0];

ws.Cells["A1"].PutValue("Docs");
var link = ws.Hyperlinks[ws.Hyperlinks.Add("A1", 1, 1, "https://docs.aspose.org/cells/net/")];
link.TextToDisplay = "Documentation";

wb.DefinedNames[wb.DefinedNames.Add("DataRange", "Sheet1!$A$1:$D$10")].Comment = "Main data range";

wb.Save("links.xlsx");
```

---

### Page Setup

`Worksheet.PageSetup` controls print margins, orientation, paper size, print area, title rows/columns, headers, footers, and page breaks. Use `PageOrientationType` and `PaperSizeType` enums.

```csharp
using Aspose.Cells_FOSS;

var wb = new Workbook();
var ps = wb.Worksheets[0].PageSetup;
ps.Orientation = PageOrientationType.Landscape;
ps.PaperSize = PaperSizeType.PaperA4;
ps.PrintArea = "$A$1:$H$50";
ps.CenterHeader = "My Report";
ps.CenterHorizontally = true;
ps.AddHorizontalPageBreak(25);

wb.Save("paged.xlsx");
```

---

### Worksheet Management

Add, rename, hide, and reorder worksheets through `WorksheetCollection`. `WorksheetCollection.Add(name)` returns the index of the new sheet. Set `Worksheet.VisibilityType` using `VisibilityType`. Merge cells with `Cells.Merge()` and control row/column sizing via `Cells.Rows` and `Cells.Columns`.

```csharp
using Aspose.Cells_FOSS;

var wb = new Workbook();
wb.Worksheets[0].Name = "Summary";
var dataIdx = wb.Worksheets.Add("Data");
wb.Worksheets[dataIdx].VisibilityType = VisibilityType.Hidden;
wb.Worksheets.ActiveSheetName = "Summary";

var ws = wb.Worksheets["Summary"];
ws.Cells["A1"].PutValue("Title");
ws.Cells.Merge(0, 0, 1, 4);
ws.Cells.Rows[0].Height = 30d;
ws.Cells.Columns[0].Width = 20d;

wb.Save("worksheets.xlsx");
```

---

### Tips and Best Practices

- Always catch `WorkbookLoadException` when loading files from user-supplied paths.
- Use `Cell.PutValue()` with the exact .NET type you intend to store — pass `decimal` for currency, `DateTime` for dates.
- Read `Cell.StringValue` for display text; use `Cell.Value` when you need the raw .NET object.
- Create conditional formatting rule sets on the widest range you need — per-row rules are expensive in large sheets.
- Call `wb.Save()` once at the end rather than after every cell write.

---

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `WorkbookLoadException` on open | Corrupt ZIP structure in XLSX | Set `LoadOptions.TryRepairPackage = true` |
| Formula returns empty `StringValue` | Formula not recalculated on load | Access `Cell.StringValue` after `Workbook.Save()` round-trip |
| Hyperlink address shows raw URL | `TextToDisplay` not set | Set `Hyperlink.TextToDisplay` after `Add()` |
| Worksheet tab not visible | `VisibilityType` set to `Hidden` | Set `ws.VisibilityType = VisibilityType.Visible` |

---

### FAQ

#### Does Aspose.Cells FOSS for .NET require Microsoft Office?

No. The library is pure managed code with no dependency on Office, Excel, or COM interop.

#### Which file formats are supported?

XLSX (read and write). CSV, ODS, PDF, and binary XLS are not supported in this release.

#### Can I use this library in a commercial application?

Yes. Aspose.Cells FOSS is published under the MIT License, which permits unrestricted commercial use with no royalties.

#### What is the minimum .NET version?

.NET 6.0 or later.

#### How do I apply a background colour to a cell?

Set `style.Pattern = FillPattern.Solid` and `style.ForegroundColor = Color.FromArgb(...)`, then call `cell.SetStyle(style)`.

---

### API Reference Summary

| Class / Method | Description |
|----------------|-------------|
| `Workbook` | Root class — create, load, save workbooks |
| `Workbook.Worksheets` | Returns the `WorksheetCollection` |
| `Workbook.Save(path)` | Saves the workbook to disk |
| `Workbook.DefinedNames` | Named ranges collection |
| `Worksheet.Cells` | Cell grid access |
| `Worksheet.ConditionalFormattings` | Conditional formatting rule sets |
| `Worksheet.Validations` | Data validation rules |
| `Worksheet.AutoFilter` | Auto-filter configuration |
| `Worksheet.Hyperlinks` | Hyperlink collection |
| `Worksheet.PageSetup` | Print layout settings |
| `Cell.PutValue()` | Write typed cell data |
| `Cell.Formula` | Excel-compatible formula string |
| `Cell.GetStyle()` / `Cell.SetStyle()` | Read/write cell style |
| `Style.Pattern` | Fill pattern (`FillPattern` enum) |
| `Style.HorizontalAlignment` | Cell alignment (`HorizontalAlignmentType`) |
| `LoadOptions` | Options for fault-tolerant file loading |

## See Also

- [Aspose.Cells for .NET — Enterprise Documentation](https://docs.aspose.com/cells/net/)
