---

page_role: howto_article
title: "Format Support -- Aspose.3D FOSS for Java"
linktitle: "Format Support"
description: >-
  Learn how to work with format support using Aspose.3D FOSS for Java.
  Covers the core API.
weight: 30
type: docs
provenance:
  content_origin: skill-generated
  last_mechanism: skill
  auto_updatable: true
  content_hash: 95d4a48e4497dd130a1cdbabbeb6155f
evidence:
  model_sha: c0ff812dacf2bf138319696f3123ae5c855ca9ea
  model_version: 26.5.0
  claims: []
  apis: []
grade: B
graded_content_hash: "f770c24e17ad3e40fc741d4dc07141cb"
grade_reasons:
  - "1 WARN finding(s) [consumer_usefulness×1] -> base grade A"
  - "US ceiling applied (WARN) -> grade capped at B"
---

Aspose.3D FOSS for Java provides classes for working with format support.

---

## Overview

| Format | Extension | Read | Write | Options class | Notes |
|--------|-----------|:----:|:-----:|---------------|-------|
| A3dw | `.a3dw` | No | Yes | `A3dwSaveOptions` | — |
| Amf | `.amf` | No | Yes | `AmfSaveOptions` | — |

**Note:** The `Pose` class API has been modified in this release.
| Collada | `.dae` | No | Yes | `ColladaSaveOptions` | Import not supported in Java edition |
| Draco   | `.drc` | No | Yes | `DracoSaveOptions`    | — |
| FBX     | `.fbx` | Yes | Yes | `FbxLoadOptions`, `FbxSaveOptions` | — |
| glTF    | `.gltf` / `.glb` | Yes | Yes | `GltfLoadOptions`, `GltfSaveOptions` | Binary GLB also supported |
| HTML5   | `.html` | No | Yes | `Html5SaveOptions`   | — |
| JT      | `.jt`   | Yes | No  | `JtLoadOptions`      | — |
| OBJ     | `.obj`  | Yes | Yes | `ObjLoadOptions`, `ObjSaveOptions` | — |
| PDF     | `.pdf`  | Yes | Yes | `PdfLoadOptions`, `PdfSaveOptions` | — |

*Note: The `Pose` API has been modified; refer to the updated API documentation for details.*
The **`Pose`** API has been modified (API MODIFIED). The supported file formats are unchanged:

| Format | Extension | Load | Save | Load/Save Options | Notes |
|--------|-----------|------|------|-------------------|-------|
| PLY    | `.ply`    | Yes  | Yes  | `PlyLoadOptions`, `PlySaveOptions` | — |
| RVM    | `.rvm`    | Yes  | Yes  | `RvmLoadOptions`, `RvmSaveOptions` | — |
| STL    | `.stl`    | Yes  | Yes  | `StlLoadOptions`, `StlSaveOptions` | — |
| U3D    | `.u3d`    | Yes  | Yes  | `U3dLoadOptions`, `U3dSaveOptions` | — |
| USD    | `.usd`    | No   | Yes  | `UsdSaveOptions`                     | — |

---

## Getting Started

Install Aspose.3D FOSS for Java:

```bash
Maven <dependency> {{< maven-gav "3d" "java" >}}
```

---

## Tips and Best Practices

- Always dispose of document objects after use
- Handle file I/O exceptions when reading or writing files
- Check the [API reference](https://reference.aspose.org/3d/java/) for the latest signatures

---

## API Reference Summary


For full details, see the [API Reference](https://reference.aspose.org/3d/java/).

## See Also

- [Aspose.3D for Java — Enterprise Documentation](https://docs.aspose.com/3d/java/)
