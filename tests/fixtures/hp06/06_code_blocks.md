---
title: "Code Blocks Test"
description: "Tests fenced and indented code blocks"
weight: 6
---

## Fenced Code Block (Backticks)

```csharp
using Aspose.Slides;

var pres = new Presentation();
pres.Save("output.pptx", SaveFormat.Pptx);
```

## Fenced Code Block with Language

```python
from aspose.slides import Presentation, SaveFormat

pres = Presentation()
pres.save("output.pptx", SaveFormat.PPTX)
```

## Multiple Code Blocks

First code example:

```javascript
const pres = new Presentation();
pres.save("output.pptx");
```

Second code example:

```java
Presentation pres = new Presentation();
pres.save("output.pptx", SaveFormat.Pptx);
```

## Code Block with Tilde Fence

~~~ruby
require 'aspose/slides'

pres = Aspose::Slides::Presentation.new
pres.save("output.pptx")
~~~

## Indented Code Block

This is a paragraph before the code.

    var pres = new Presentation();
    pres.Save("output.pptx", SaveFormat.Pptx);

This is a paragraph after the code.

## Code Block in List

1. Install the library
2. Create a presentation:

   ```csharp
   var pres = new Presentation();
   ```

3. Save the file

## Mixed Inline and Block Code

Use the `SaveFormat.Pptx` format to save presentations:

```csharp
pres.Save("output.pptx", SaveFormat.Pptx);
```

You can also use `SaveFormat.Pdf` for PDF export.

## Code Block with Special Characters

```csharp
// Special characters in code
string path = @"C:\Users\Documents\presentation.pptx";
string template = $"Slide {index} of {total}";
var regex = new Regex(@"\b\d{3}-\d{4}\b");
```

## Code Block with HTML

```html
<div class="container">
  <h1>Title</h1>
  <p>Content with <strong>bold</strong> text.</p>
</div>
```

## Code Block with XML

```xml
<?xml version="1.0" encoding="UTF-8"?>
<presentation>
  <slide id="1">
    <title>Hello World</title>
  </slide>
</presentation>
```

## Empty Code Block

```

```

## Code Block with Only Whitespace

```


```
