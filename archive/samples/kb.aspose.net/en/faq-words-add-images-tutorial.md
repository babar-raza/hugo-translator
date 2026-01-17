---
title: "FAQ - Add Images to Word Documents in C# (Sample Live)"
description: "Sample live-test FAQ answering common questions about the KB tutorial for inserting images into Word documents using C#."
sample_type: "live_test"
source_url: "https://kb.aspose.com/words/"
---

## Getting Started

**Q1. Which Aspose product do I need to add images to Word documents?**  
The KB article is based on **Aspose.Words for .NET**, which provides classes like `Document` and `DocumentBuilder` for manipulating Word documents.  
Additional context and installation instructions are available on the Aspose.Words documentation site at [docs.aspose.com/words/net](https://docs.aspose.com/words/net/).

**Q2. Do I need any special assemblies or packages?**  
Yes. The tutorial references `System.Drawing` and requires the Aspose.Words for .NET NuGet package.  
These prerequisites are listed in the numbered steps of the KB article under `content/kb.aspose.net/words/en/how-to-add-images-word-documents-csharp.md`.

## Implementation Details

**Q3. How are images inserted into a Word document?**  
The KB example shows how to create a `DocumentBuilder`, move the cursor to the appropriate location, and call `InsertImage` with a file path or stream.  
After insertion, formatting properties on the resulting `Shape` can be adjusted for size, position, and layout.

**Q4. Can I add images to headers and footers?**  
Yes. The tutorial explains that you can move the builder cursor into the header or footer before calling `InsertImage`.  
This allows you to place logos or branding elements across all pages in the document.

## Output and Deployment

**Q5. In which formats can I save the updated document?**  
Using `Document.Save`, you can export to formats like DOCX, DOC, PDF, and others supported by Aspose.Words.  
The precise options are documented in the Aspose.Words file format support section on [docs.aspose.com](https://docs.aspose.com/words/net/getting-started/file-formats/).

**Q6. Where can I find the complete code sample?**  
The full code listing is included in the KB article and may also be mirrored in sample projects linked from the documentation.  
Links to related examples are typically provided near the end of the tutorial on [kb.aspose.com](https://kb.aspose.com/words/).

