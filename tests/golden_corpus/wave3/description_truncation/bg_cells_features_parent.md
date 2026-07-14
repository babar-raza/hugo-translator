---
page_role: howto_article
title: Характеристики на продукта
description: 'Обзор на всички основни възможности в Aspose.Cells FOSS за .NET: I/O на работната книга, данни от клетки, стилизиране, условно форматиране (условно оформление), валидиране , автоматичен филтриране на файлове, хипервръзки (хиперсвързвания), настройка на страници и управление на работни листове.'
weight: 10
type: docs
provenance:
    content_origin: skill-generated
    last_mechanism: manual-edit-skill
    reviewed: false
    content_created_at: '2026-04-07'
    auto_updatable: true
    content_hash: 4901382a10eb9f61cbd3740cfc9291ae
evidence:
    model_sha: 4884d3fe7148ec040e391359469b8feaa52cc782
    model_version: ''
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
      - Workbook.DefinedNames
      - Workbook.Save
      - Workbook.Worksheets
    formats:
      - ext: auto
        support: import
      - ext: xlsx
        support: import
    sections:
      - heading: Features
        line: 200
        claims: []
        apis: []
        formats:
          - ext: xlsx
            support: import
      - heading: Workbook Create, Load, and Save
        line: 206
        claims:
          - CLM-cells-160083
          - CLM-cells-409d21
        apis:
          - Workbook.Save
          - Workbook.Worksheets
        formats:
          - ext: xlsx
            support: import
      - heading: Cell Data and Formulas
        line: 233
        claims:
          - CLM-cells-160083
          - CLM-cells-409d21
        apis:
          - Workbook.Save
          - Workbook.Worksheets
        formats:
          - ext: xlsx
            support: import
      - heading: Cell Styling
        line: 258
        claims:
          - CLM-cells-160083
          - CLM-cells-409d21
        apis:
          - FillPattern.Solid
          - HorizontalAlignmentType.Center
          - Workbook.Save
          - Workbook.Worksheets
        formats:
          - ext: xlsx
            support: import
      - heading: Conditional Formatting
        line: 282
        claims:
          - CLM-cells-160083
          - CLM-cells-3fca6b
          - CLM-cells-409d21
        apis:
          - CellArea.CreateCellArea
          - FillPattern.Solid
          - FormatConditionType.CellValue
          - OperatorType.Between
          - Workbook.Save
          - Workbook.Worksheets
        formats:
          - ext: xlsx
            support: import
      - heading: Data Validation
        line: 307
        claims:
          - CLM-cells-160083
          - CLM-cells-3fca6b
          - CLM-cells-409d21
        apis:
          - CellArea.CreateCellArea
          - OperatorType.Between
          - ValidationType.Decimal
          - ValidationType.List
          - Workbook.Save
          - Workbook.Worksheets
        formats:
          - ext: xlsx
            support: import
      - heading: Auto-Filter
        line: 334
        claims:
          - CLM-cells-160083
          - CLM-cells-409d21
        apis:
          - Workbook.Save
          - Workbook.Worksheets
        formats:
          - ext: xlsx
            support: import
      - heading: Hyperlinks and Defined Names
        line: 357
        claims:
          - CLM-cells-160083
          - CLM-cells-409d21
          - CLM-cells-9cbe22
        apis:
          - Workbook.DefinedNames
          - Workbook.Save
          - Workbook.Worksheets
        formats:
          - ext: xlsx
            support: import
      - heading: Page Setup
        line: 378
        claims:
          - CLM-cells-160083
          - CLM-cells-409d21
        apis:
          - PageOrientationType.Landscape
          - PaperSizeType.PaperA4
          - Workbook.Save
          - Workbook.Worksheets
        formats:
          - ext: xlsx
            support: import
      - heading: Worksheet Management
        line: 399
        claims:
          - CLM-cells-0ff38d
          - CLM-cells-160083
          - CLM-cells-409d21
        apis:
          - Cells.Merge
          - VisibilityType.Hidden
          - Workbook.Save
          - Workbook.Worksheets
        formats:
          - ext: xlsx
            support: import
      - heading: Common Issues
        line: 433
        claims: []
        apis: []
        formats:
          - ext: xlsx
            support: import
      - heading: FAQ
        line: 444
        claims: []
        apis: []
        formats:
          - ext: xlsx
            support: import
      - heading: API Reference Summary
        line: 468
        claims: []
        apis: []
        formats:
          - ext: auto
            support: import
grade: A
graded_at: "2026-04-15T11:35:55Z"
graded_content_hash: "4901382a10eb9f61"
graded_model_sha: 4884d3fe7148ec040e391359469b8feaa52cc782
graded_evaluators: audit
graded_logic_version: 7
---

## Характеристики на продукта

Aspose.Cells FOSS for .NET is a pure managed .NET library for creating, reading, and modifying Excel XLSX spreadsheets. The entry point is the `Workbook` class, който предоставя достъп до работни листове, дефинирани имена и операции за съхранение/зареждане. Тази страница обобщава всяка важна област с кратки примери на кода.

---

### Схема за създаване, зареждане и съхранение

Създаване на нова работна книга с: `new Workbook()`. Заредете съществуващ XLSX файл, като предадете път на файла към конструктора. Използвайте `LoadOptions` За да се даде възможност за толерантно натоварване. `Workbook.Save(path)` да се запазят промените.

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

### Данни и формули на клетките

Използване на: `Cell.PutValue()` да пишеш нишки, цели числа, десетичници, булеви и `DateTime` Възстановяване на стойности. `Cell.Formula` за да се назначи синхрон от формули, съвместими с Excel. Прочетете обратно текста на дисплея чрез `Cell.StringValue` и суровата стойност чрез: `Cell.Value`.

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

### Стилиране на клетките

Изтегляне и изменение на файла. `Style` обект за всяка клетка с: `Cell.GetStyle()` и в) `Cell.SetStyle()`.- Да, това е. `Style` клас предоставя: `Font` (с черна дума, курсив, размер, име), `ForegroundColor`, `Pattern` (на тип: `FillPattern`), `HorizontalAlignment` (с помощта на: `HorizontalAlignmentType`), и граничен контрол чрез `Borders`.

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

### Условно форматиране

`Worksheet.ConditionalFormattings` връща a `ConditionalFormattingCollection`.Обади се. `Add()` да създадем набор от правила, след това `AddCondition()` да добавите правила, използвайки: `FormatConditionType` и в) `OperatorType`.Типовете поддържани условия включват: `CellValue`, `Expression`, `ColorScale`, `DataBar`, и `IconSet`.

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

### Валидиране на данните

`Worksheet.Validations` връща a `ValidationCollection`.Обади се. `Add(CellArea)` да се създаде `Validation` за обхват на клетките. `Type` собственост, използваща `ValidationType` (`List`, `Decimal`, или `Custom`). Конфигуриране `Formula1`, `Formula2`, `Operator`, `InputTitle`, `InputMessage`, `ErrorTitle`, и `ErrorMessage`.

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

### Автоматичен филтър

`Worksheet.AutoFilter` излага на показния `AutoFilter` Общ обект. `AutoFilter.Range` да определите диапазона на реда заглавие. Access `AutoFilter.FilterColumns` (събиране) и повикване на `Add(columnIndex)` да активира филтриране на конкретна колона.

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

### Хипервръзки и дефинирани имена

`Worksheet.Hyperlinks` е един от следните: `HyperlinkCollection`.Обади се. `Add()` за вмъкване на външни URL адреси, вътрешни препратки към клетки или връзки mailto. `Hyperlink.TextToDisplay` и в) `Hyperlink.ScreenTip` за текст, изпратен към потребителя. `Workbook.DefinedNames` е един от следните: `DefinedNameCollection`; обаждане `Add(name, refersTo)` да създавате кръгове с имена.

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

### Настройка на страницата

`Worksheet.PageSetup` Контролира маржовете на печат, ориентацията, размера на хартията, площта за печатане, редките/колоните с заглавия, надписа и прекъсванията. `PageOrientationType` и в) `PaperSizeType` - Да, сър.

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

### Управление на работния лист

Добавяне, преименуване на имена, скриване и реордиране на работни листове чрез `WorksheetCollection`. `WorksheetCollection.Add(name)` Връща индекса на новия лист. `Worksheet.VisibilityType` използване на: `VisibilityType`.Сливане на клетките с `Cells.Merge()` и контрол на размера на реда/колоните чрез: `Cells.Rows` и в) `Cells.Columns`.

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

### Съвети и най-добри практики

- Винаги хващаш. `WorkbookLoadException` при зареждане на файлове от пътеки, предоставени от потребителя.
- Използване на: `Cell.PutValue()` с точния .NET тип, който възнамерявате да съхраните  pass `decimal` за валута, `DateTime` За срещи.
- Прочети. `Cell.StringValue` за показване на текст; използване `Cell.Value` когато се нуждаете от суровия .NET обект.
- Създаване на набори от правила за условно форматиране в най-широкия необходим диапазон  правилата по ред са скъпи при големи листове.
- Обади се. `wb.Save()` веднъж в края, а не след всяка клетка.

---

### Общи проблеми

| Издание                                             | Причина за това                          | Ремонтиране                                                                            |
| --------------------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------- |
| `WorkbookLoadException` на открито                  | Покварена ZIP структура в XLSX           | Настройка `LoadOptions.TryRepairPackage = true`                                        |
| Формулата връща празно `StringValue`                | Формула, не преизчислена при натоварване | Достъп до информация `Cell.StringValue` след това `Workbook.Save()` пътуване и връщане |
| Адресът на хипервръзката показва суровия URL адрес. | `TextToDisplay` не е зададен             | Настройка `Hyperlink.TextToDisplay` след това `Add()`                                  |
| Таблицата не е видима                               | `VisibilityType` настройка към: `Hidden` | Настройка `ws.VisibilityType = VisibilityType.Visible`                                 |

---

### FAQ

#### За да се използва Aspose.Cells FOSS за .NET, трябва ли Microsoft Office?

Библиотеката е чист управляван код без зависимост от Office, Excel или COM интерфейс.

#### Какви формати на файлове се поддържат?

CSV, ODS, PDF и двоичен XLS не се поддържат в това издание.

#### Мога ли да използвам тази библиотека в търговско приложение?

Да. Aspose.Cells FOSS е публикуван под лиценза на MIT, който позволява неограничено търговско използване без авторски права.

#### Каква е минималната версия на .NET?

.NET 6.0 или по-нови.

#### Как да приложа цвят на фона към клетка?

Настройка `style.Pattern = FillPattern.Solid` и в) `style.ForegroundColor = Color.FromArgb(...)`, тогава се обади. `cell.SetStyle(style)`.

---

### Снимка на API референтна информация

| Клас / метод                          | Описание на състоянието                                       |
| ------------------------------------- | ------------------------------------------------------------- |
| `Workbook`                            | Корен клас  създаване, зареждане и запазване на работни книги |
| `Workbook.Worksheets`                 | Връща се: `WorksheetCollection`                               |
| `Workbook.Save(path)`                 | Съхранява работната книга на диск                             |
| `Workbook.DefinedNames`               | Събиране на наименовани диапазони                             |
| `Worksheet.Cells`                     | Достъп до мобилна мрежа                                       |
| `Worksheet.ConditionalFormattings`    | Набор на правила за форматиране с условия                     |
| `Worksheet.Validations`               | Правила за валидиране на данни                                |
| `Worksheet.AutoFilter`                | Конфигурация на автоматичния филтър                           |
| `Worksheet.Hyperlinks`                | Сборник на хипервръзки                                        |
| `Worksheet.PageSetup`                 | Настройки за оформление на печат                              |
| `Cell.PutValue()`                     | Записване на вписани данни от клетка                          |
| `Cell.Formula`                        | Свързваща се с Excel формула                                  |
| `Cell.GetStyle()` / `Cell.SetStyle()` | Стил за четене/записване на клетка                            |
| `Style.Pattern`                       | Модел за попълване (`FillPattern` еум)                        |
| `Style.HorizontalAlignment`           | Насочване на клетките (`HorizontalAlignmentType`)             |
| `LoadOptions`                         | Опции за зареждане на файлове с толерантност към грешки       |

