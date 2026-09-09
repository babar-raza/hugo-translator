---
page_role: howto_article
title: Scene Management
description: >-
  Create, open, merge, and save Aspose.3D scenes in .NET — loading files with
  Scene.Open, saving with Scene.Save, clearing scene content, and managing
  asset information and metadata.
type: docs
weight: 30
evidence:
  model_sha: 70933ab13eb0e313d9b160c55845011d366b1599
  model_version: 1.0.0
  claims:
  - CLM-3d-00fbda
  - CLM-3d-0126d9
  - CLM-3d-015f93
  - CLM-3d-4e6301
  - CLM-3d-4f8d1a
  - CLM-3d-a572d1
  - CLM-3d-cf1f1a
  - ERC-3d-net-214f7df6
  apis:
  - AssetInfo
  - FileFormat.FBX7700Binary
  - FileFormat.GLTF2_Binary
  - FileFormat.STLBinary
  - FileFormat.WavefrontOBJ
  - Node
  - ObjSaveOptions
  - Scene
  - Scene.AssetInfo
  - Scene.Clear
  - Scene.FromFile
  - Scene.Open
  - Scene.Save
  formats:
  - ext: collada
    support: both
  - ext: fbx
    support: both
  - ext: obj
    support: both
  - ext: stl
    support: both
  - ext: gltf
    support: both
  sections:
  - heading: Scene Management
    line: 129
    claims:
    - ERC-3d-net-214f7df6
    apis:
    - Scene
  - heading: Creating and Opening Scenes
    line: 135
    claims:
    - CLM-3d-0126d9
    - CLM-3d-015f93
    - ERC-3d-net-214f7df6
    apis:
    - FileFormat.STLBinary
    - FileFormat.WavefrontOBJ
    - Scene
    - Scene.FromFile
    - Scene.Open
    formats:
    - ext: fbx
      support: both
    - ext: obj
      support: both
    - ext: stl
      support: both
  - heading: Saving Scenes
    line: 162
    claims: []
    apis:
    - FileFormat.FBX7700Binary
    - FileFormat.GLTF2_Binary
    - ObjSaveOptions
    formats:
    - ext: fbx
      support: both
    - ext: obj
      support: both
    - ext: gltf
      support: both
  - heading: Clearing Scene Content
    line: 185
    claims:
    - CLM-3d-cf1f1a
    - ERC-3d-net-214f7df6
    apis:
    - Scene
    - Scene.Clear
  - heading: Scene Metadata
    line: 201
    claims:
    - CLM-3d-00fbda
    - CLM-3d-4f8d1a
    apis:
    - AssetInfo
    - Scene.AssetInfo
    - Scene.Save
    formats:
    - ext: collada
      support: both
    - ext: fbx
      support: both
    - ext: gltf
      support: both
  - heading: API Quick Reference
    line: 223
    claims: []
    apis:
    - Node
provenance:
  content_origin: skill-generated
  last_mechanism: manual-edit-skill
  auto_updatable: true
  content_hash: c549a4dfde0e3fdb25166153927202a5
  content_created_at: '2026-07-12T00:00:00+00:00'
  reviewed: false
grade: B
graded_content_hash: "c549a4dfde0e3fdb25166153927202a5"
grade_reasons:
  - "3 WARN finding(s) [audit] -> base grade B"
---

## Scene Management

The `Scene` class is the entry point for all 3D content in Aspose.3D for .NET. It provides methods to create scenes from scratch, load existing files in any supported format, save to any target format, and inspect scene metadata.

---

### Creating and Opening Scenes

Create an empty scene with `new Scene()`, or load from a file:

```csharp
using Aspose.ThreeD;

// Empty scene
var empty = new Scene();

// Load from file — format is detected automatically
var scene = Scene.FromFile("model.fbx");

// Load using Scene.Open with explicit format
var scene2 = new Scene();
scene2.Open("model.obj", FileFormat.WavefrontOBJ);

// Load from a stream (useful when reading from memory or network)
using var stream = System.IO.File.OpenRead("model.stl");
var scene3 = new Scene();
scene3.Open(stream, FileFormat.STLBinary);
```

`Scene.FromFile` auto-detects the format from the file extension and magic bytes. Use the `FileFormat` overload when the extension is ambiguous or absent.

---

### Saving Scenes

Save a scene to a file or stream in any supported output format:

```csharp
// Save to file — format determined from extension
scene.Save("output.gltf");

// Save with explicit format
scene.Save("output.bin", FileFormat.GLTF2_Binary);

// Save to a stream
using var output = System.IO.File.Create("output.fbx");
scene.Save(output, FileFormat.FBX7700Binary);

// Save with format-specific options
var opts = new Aspose.ThreeD.Formats.ObjSaveOptions();
opts.PointCloud = false;
scene.Save("output.obj", opts);
```

---

### Clearing Scene Content

To remove all nodes and assets from a scene while retaining the `Scene` object:

```csharp
// Remove all direct children of the root node
scene.RootNode.ChildNodes.Clear();

// Or replace the scene entirely
scene = new Scene();
```

`Scene.Clear()` is available and clears the scene content, restoring default settings; alternatively, create a new `Scene` instance as shown above.

---

### Scene Metadata

The `AssetInfo` property on a `Scene` exposes metadata embedded in supported formats (FBX, Collada, glTF):

```csharp
var info = scene.AssetInfo;
Console.WriteLine("Author:       " + info.Author);
Console.WriteLine("Creation UTC: " + info.CreationTime);
Console.WriteLine("Units:        " + info.UnitName + " @ " + info.UnitScaleFactor);
```

Set metadata before saving to preserve it in the output file:

```csharp
scene.AssetInfo.ApplicationName = "My Application 1.0";
scene.AssetInfo.UnitName = "meter";
scene.AssetInfo.UnitScaleFactor = 1.0;
scene.Save("output_with_meta.fbx");
```

---

### API Quick Reference

| Member | Description |
|---|---|
| `new Scene()` | Create an empty scene |
| `Scene.FromFile(path)` | Static helper: open a file and return the loaded scene |
| `scene.Open(path, format?)` | Load a file into an existing scene |
| `scene.Open(stream, format)` | Load from a stream |
| `scene.Save(path, format?)` | Save to a file |
| `scene.Save(stream, format)` | Save to a stream |
| `scene.RootNode` | Root `Node` of the scene hierarchy |
| `scene.AssetInfo` | Metadata block (creator, timestamps, units) |
| `scene.AssetInfo.ApplicationName` | Application name embedded in the file |
| `scene.AssetInfo.UnitScaleFactor` | Scene unit scale relative to meters |

## See Also

- [Aspose.3D for .NET — Enterprise Documentation](https://docs.aspose.com/3d/net/)
- [Working with the Scene Graph](scene-graph) — navigate and modify the node hierarchy
- [Format Support](format-support) — all supported input and output formats
