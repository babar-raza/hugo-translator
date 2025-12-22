---
title: Code Blocks Test
description: Tests code block preservation
---

## Inline Code

Use the `SaveFormat.Pptx` format for PowerPoint files.

The `Aspose.Slides.LowCode.Convert` method is simple.

## Fenced Code Blocks

```csharp
using Aspose.Slides;

var presentation = new Presentation();
presentation.Save("output.pptx", SaveFormat.Pptx);
```

```python
from aspose.slides import Presentation, SaveFormat

pres = Presentation()
pres.save("output.pptx", SaveFormat.PPTX)
```

## Code Block Without Language

```
This is plain code without language specification.
Preserve exactly as-is.
```

## Indented Code Block

    This is an indented code block.
    It should also be preserved.
