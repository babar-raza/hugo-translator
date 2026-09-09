---
page_role: howto_article
title: Working with glTF and GLB
description: >-
  Load, save, and configure glTF 2.0 and GLB files in Aspose.3D for .NET —
  controlling embedded textures, Draco compression, and format-specific save
  options via GltfLoadOptions and GltfSaveOptions.
type: docs
weight: 90
evidence:
  model_sha: 70933ab13eb0e313d9b160c55845011d366b1599
  model_version: 1.0.0
  claims:
  - CLM-3d-00fbda
  - CLM-3d-0126d9
  - CLM-3d-015f93
  - CLM-3d-24314f
  - CLM-3d-4e6301
  - CLM-3d-51b673
  - CLM-3d-8326ba
  - CLM-3d-b6e423
  - CLM-3d-d10b2d
  - ERC-3d-net-214f7df6
  - ERC-3d-net-d45be5bc
  apis:
  - Box
  - FileFormat.GLTF2
  - FileFormat.GLTF2_Binary
  - GltfEmbeddedImageFormat
  - GltfEmbeddedImageFormat.Jpeg
  - GltfLoadOptions
  - GltfSaveOptions
  - GltfSaveOptions.EmbedAssets
  - GltfSaveOptions.ImageFormat
  - Scene
  - Scene.FromFile
  - Scene.Open
  - Scene.RootNode
  - Scene.Save
  formats:
  - ext: gltf
    support: both
  - ext: draco
    support: export
  sections:
  - heading: Working with glTF and GLB
    line: 128
    claims:
    - ERC-3d-net-d45be5bc
    apis:
    - GltfLoadOptions
    - GltfSaveOptions
    formats:
    - ext: gltf
      support: both
  - heading: Loading a glTF File
    line: 134
    claims:
    - CLM-3d-0126d9
    - CLM-3d-015f93
    - ERC-3d-net-214f7df6
    apis:
    - GltfLoadOptions
    - Scene
    - Scene.FromFile
    - Scene.Open
    formats:
    - ext: gltf
      support: both
  - heading: Saving as glTF or GLB
    line: 155
    claims:
    - CLM-3d-00fbda
    - CLM-3d-4e6301
    - CLM-3d-8326ba
    - ERC-3d-net-214f7df6
    - ERC-3d-net-d45be5bc
    apis:
    - Box
    - FileFormat.GLTF2
    - FileFormat.GLTF2_Binary
    - GltfSaveOptions
    - GltfSaveOptions.EmbedAssets
    - Scene
    - Scene.RootNode
    - Scene.Save
    formats:
    - ext: gltf
      support: both
  - heading: Controlling Embedded Image Format
    line: 180
    claims:
    - CLM-3d-00fbda
    - CLM-3d-24314f
    - ERC-3d-net-d45be5bc
    apis:
    - FileFormat.GLTF2_Binary
    - GltfEmbeddedImageFormat.Jpeg
    - GltfSaveOptions
    - GltfSaveOptions.ImageFormat
    - Scene.Save
    formats:
    - ext: gltf
      support: both
  - heading: API Quick Reference
    line: 198
    claims: []
    apis:
    - FileFormat.GLTF2
    - FileFormat.GLTF2_Binary
    - GltfEmbeddedImageFormat
    formats:
    - ext: gltf
      support: both
provenance:
  content_origin: skill-generated
  last_mechanism: manual-edit-skill
  auto_updatable: true
  content_hash: f435c1f7874ba6934c4060cc8be5d334
  content_created_at: '2026-07-12T00:00:00+00:00'
  reviewed: false
grade: A
graded_content_hash: "f435c1f7874ba6934c4060cc8be5d334"
grade_reasons:
  - "2 WARN finding(s) [audit] -> base grade A"
---

## Working with glTF and GLB

Aspose.3D for .NET supports reading and writing glTF 2.0 (`.gltf` with separate assets) and GLB (single-file binary glTF). Use `GltfLoadOptions` to configure loading behaviour and `GltfSaveOptions` to control export output.

---

### Loading a glTF File

Load a `.gltf` or `.glb` file directly with `Scene.Open`. Supply `GltfLoadOptions` for finer control:

```csharp
using Aspose.ThreeD;
using Aspose.ThreeD.Formats;

// Basic load
var scene = Scene.FromFile("model.gltf");

// Load with options
var opts = new GltfLoadOptions();
var sceneWithOpts = new Scene();
sceneWithOpts.Open("model.gltf", opts);
```

> glTF files reference external `.bin` buffers and textures by relative path. Keep all referenced assets in the same directory as the `.gltf` file when loading.

---

### Saving as glTF or GLB

Save any scene as glTF or the compact binary GLB format:

```csharp
using Aspose.ThreeD;
using Aspose.ThreeD.Formats;

var scene = new Scene();
scene.RootNode.CreateChildNode("box", new Aspose.ThreeD.Entities.Box());

// Save as glTF (separate JSON + .bin buffer)
scene.Save("output.gltf", FileFormat.GLTF2);

// Save as GLB (single binary file)
scene.Save("output.glb", FileFormat.GLTF2_Binary);

// Save with custom options — embed the binary buffer inside the JSON
var saveOpts = new GltfSaveOptions(FileFormat.GLTF2);
saveOpts.EmbedAssets = true;
scene.Save("output_embedded.gltf", saveOpts);
```

---

### Controlling Embedded Image Format

When textures are embedded, control how image data is stored with `GltfEmbeddedImageFormat`:

```csharp
var saveOpts = new GltfSaveOptions(FileFormat.GLTF2_Binary);
saveOpts.ImageFormat = GltfEmbeddedImageFormat.Jpeg;
scene.Save("output.glb", saveOpts);
```

| `GltfEmbeddedImageFormat` value | Description |
|---|---|
| `Jpeg` | Re-encode embedded textures as JPEG (lossy, smaller) |
| `Png` | Re-encode embedded textures as PNG (lossless) |
| `NoChange` | Keep original encoding (default) |

---

### API Quick Reference

| Member | Description |
|---|---|
| `new GltfLoadOptions()` | Configure glTF import |
| `new GltfSaveOptions(format)` | Configure glTF/GLB export |
| `saveOpts.EmbedAssets` | Embed binary buffer inside the `.gltf` JSON |
| `saveOpts.ImageFormat` | Embedded texture encoding (`GltfEmbeddedImageFormat`) |
| `FileFormat.GLTF2` | Target format: separate `.gltf` + `.bin` |
| `FileFormat.GLTF2_Binary` | Target format: single `.glb` |

## See Also

- [Aspose.3D for .NET — Enterprise Documentation](https://docs.aspose.com/3d/net/)
- [Format Support](format-support) — full list of supported 3D formats
