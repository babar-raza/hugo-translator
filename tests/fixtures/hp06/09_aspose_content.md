---
title: "Aspose-Specific Content Test"
description: "Tests Aspose product names, API references, and typical patterns"
weight: 9
---

## Product Names

### Aspose Products

This document covers **Aspose.Slides** for .NET.

You can also use **Aspose.Cells** for spreadsheets.

For PDF processing, see **Aspose.PDF** for .NET.

Word document processing is handled by **Aspose.Words**.

### Product Variations

Install **Aspose.Slides for .NET** version 24.1 or later.

Use **Aspose.Slides for Java** in Java applications.

Try **Aspose.Slides for Python** via .NET.

Check out **Aspose.Slides for C++** for native applications.

### LowCode APIs

The **Aspose.Slides.LowCode** API provides simplified methods.

Use **Aspose.Cells.LowCode** for spreadsheet operations.

The **Aspose.PDF.LowCode** namespace simplifies PDF tasks.

## API References

### Class Names

Create a new **`Presentation`** instance.

Use the **`Slide`** class to access slides.

The **`Shape`** class represents shapes on slides.

Work with **`TextFrame`** for text content.

### Method Names

Call the **`Presentation.Save()`** method to save files.

Use **`Presentation.Load()`** to load existing presentations.

The **`Slide.AddClone()`** method duplicates slides.

Call **`Shape.RemoveAt()`** to delete shapes.

### Property Names

Set the **`Presentation.SlideSize`** property.

Access **`Slide.Background`** to modify backgrounds.

Use **`Shape.TextFrame.Text`** to get text content.

Modify **`Paragraph.Alignment`** for text alignment.

### Enum Values

Use **`SaveFormat.Pptx`** for PowerPoint 2007+ format.

Save as **`SaveFormat.Pdf`** for PDF export.

Export to **`SaveFormat.Odp`** for OpenDocument format.

Use **`SaveFormat.Ppt`** for PowerPoint 97-2003 format.

### Namespace References

Import the **`Aspose.Slides`** namespace.

Use **`Aspose.Slides.Export`** for export functionality.

The **`Aspose.Slides.Charts`** namespace handles charts.

Work with **`Aspose.Slides.SmartArt`** for diagrams.

## Typical Code Patterns

### Basic Usage

```csharp
using Aspose.Slides;

var pres = new Presentation();
pres.Save("output.pptx", SaveFormat.Pptx);
```

### Loading Presentations

Use **`Presentation.Load()`** to load existing files:

```csharp
var pres = new Presentation("input.pptx");
```

### Slide Manipulation

Add slides using the **`Slides`** collection:

```csharp
var slide = pres.Slides.AddEmptySlide(layout);
```

## Development Tools

### IDEs

Install **Visual Studio** 2019 or later.

You can also use **Visual Studio Code** with extensions.

For Java, use **IntelliJ IDEA** or **Eclipse**.

### Frameworks

Target **.NET 6.0+** for modern applications.

Support for **.NET Framework 4.0+** is available.

Works with **.NET Core 3.1+** and later.

Compatible with **.NET Standard 2.0** libraries.

### NuGet Packages

Install via NuGet: **`Aspose.Slides`** package.

For Python: **`aspose-slides`** package.

Java users: **`aspose-slides-java`** artifact.

## File Formats

### Input Formats

Supports **PPTX** (PowerPoint 2007+).

Reads **PPT** (PowerPoint 97-2003).

Loads **ODP** (OpenDocument Presentation).

Imports **PPTM** (macro-enabled presentations).

### Output Formats

Save as **PPTX**, **PPT**, **PDF**, **HTML**, **SVG**.

Export to **PNG**, **JPEG**, **TIFF** images.

Convert to **ODP**, **PPTM**, **POTX** formats.

## Common Patterns in Documentation

### Prerequisites

1. Install **Visual Studio** 2019 or later
2. Target **.NET 6.0+**, **.NET Framework 4.0+**, or **.NET Core 3.1+**
3. Install **Aspose.Slides for .NET** via NuGet

### Step-by-Step Instructions

1. Create a new **`Presentation`** instance
2. Add slides using **`Slides.AddEmptySlide()`**
3. Save with **`Presentation.Save()`** method
4. Use **`SaveFormat.Pptx`** for output format

### Links to Resources

Visit **[Aspose.Slides Documentation](https://docs.aspose.com/slides/net/)** for guides.

Check the **[API Reference](https://reference.aspose.com/slides/net/)** for details.

Download from **[releases page](https://releases.aspose.com/slides/net/)**.

Get support at **[Aspose Forum](https://forum.aspose.com/c/slides)**.

## Product Names with Versions

Install **Aspose.Slides 24.1** or later.

Requires **Visual Studio 2019** or **Visual Studio 2022**.

Compatible with **.NET 6.0+** and **. NET Framework 4.6.1+**.

Works with **PowerPoint 2007** through **PowerPoint 2021**.

## Complex Real-World Sentences

The **Aspose.Slides.LowCode** API provides streamlined methods for common tasks.

Use the **`Presentation.Save()`** method with **`SaveFormat.Pptx`** to export.

Install **Visual Studio 2019** or later and target **.NET 6.0+** for best results.

Visit **[our documentation](https://docs.aspose.com)** and check `Presentation.Save()`.
