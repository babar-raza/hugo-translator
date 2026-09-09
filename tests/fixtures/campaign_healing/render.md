---
page_role: howto_article
title: Rendering 3D Scenes
description: >-
  Render 3D scenes to image files in Aspose.3D for .NET — configuring the
  Camera, setting up Light sources, specifying ImageRenderOptions, and
  saving rendered output to disk.
type: docs
weight: 50
evidence:
  model_sha: 70933ab13eb0e313d9b160c55845011d366b1599
  model_version: 1.0.0
  claims:
  - CLM-3d-25c7f2
  - CLM-3d-3f7144
  - CLM-3d-4473e6
  - CLM-3d-478a3f
  - CLM-3d-4e6301
  - CLM-3d-811edc
  - CLM-3d-9fdfe0
  - CLM-3d-c29f18
  - CLM-3d-e6c15a
  - ERC-3d-net-214f7df6
  - ERC-3d-net-451b79eb
  - ERC-3d-net-4eb5f6e9
  - ERC-3d-net-b462888b
  - ERC-3d-net-c580ee7c
  apis:
  - Camera
  - Camera.FarPlane
  - Camera.FieldOfViewY
  - Camera.NearPlane
  - ImageRenderOptions
  - Light
  - Light.Color
  - Light.Intensity
  - Light.LightType
  - LightType.Directional
  - LightType.Point
  - ProjectionType.Orthographic
  - ProjectionType.Perspective
  - Renderer
  - Scene
  - Scene.Render
  - Scene.RootNode
  - Transform
  - Vector2
  - Vector3
  sections:
  - heading: Rendering 3D Scenes
    line: 59
    claims:
    - ERC-3d-net-451b79eb
    - ERC-3d-net-4eb5f6e9
    - ERC-3d-net-c580ee7c
    apis:
    - Camera
    - ImageRenderOptions
    - Light
    - Renderer
  - heading: Setting Up a Camera
    line: 65
    claims:
    - CLM-3d-478a3f
    - CLM-3d-4e6301
    - ERC-3d-net-214f7df6
    - ERC-3d-net-b462888b
    - ERC-3d-net-c580ee7c
    apis:
    - Camera
    - Camera.FarPlane
    - Camera.FieldOfViewY
    - Camera.NearPlane
    - ProjectionType.Orthographic
    - ProjectionType.Perspective
    - Scene
    - Scene.RootNode
    - Transform
    - Vector3
  - heading: Adding Lights
    line: 93
    claims:
    - CLM-3d-3f7144
    - CLM-3d-4e6301
    - CLM-3d-c29f18
    - CLM-3d-e6c15a
    apis:
    - Light
    - Light.Color
    - Light.Intensity
    - Light.LightType
    - LightType.Directional
    - LightType.Point
    - Scene.RootNode
    - Vector3
  - heading: Rendering to an Image File
    line: 117
    claims:
    - CLM-3d-4473e6
    - ERC-3d-net-451b79eb
    apis:
    - ImageRenderOptions
    - Scene.Render
    - Vector2
  - heading: API Quick Reference
    line: 133
    claims:
    - ERC-3d-net-b462888b
    apis:
    - ProjectionType.Perspective
    - Vector2
    - Vector3
provenance:
  content_origin: skill-generated
  last_mechanism: skill
  auto_updatable: true
  content_hash: c095f865999b9ddef7cbf3bafc077f55
  content_created_at: '2026-07-12T00:00:00+00:00'
grade: A
graded_content_hash: "c095f865999b9ddef7cbf3bafc077f55"
grade_reasons:
  - "No findings -> grade A"
---

## Rendering 3D Scenes

Aspose.3D for .NET can render a scene to a raster image. The render pipeline requires a `Camera` (point of view), one or more `Light` sources, and `ImageRenderOptions` (output resolution and format). The `Renderer` class drives the render pass.

---

### Setting Up a Camera

Add a `Camera` entity to a scene node. Set the camera's position through the node's `Transform`, and point it at a target using `LookAt`:

```csharp
using Aspose.ThreeD;
using Aspose.ThreeD.Entities;
using Aspose.ThreeD.Utilities;

var scene = new Scene();

// Create the camera entity
var camera = new Camera(ProjectionType.Perspective);
camera.NearPlane = 0.1;
camera.FarPlane = 1000.0;
camera.FieldOfViewY = 45.0;

// Attach to a node and position it
Node cameraNode = scene.RootNode.CreateChildNode("main_camera", camera);
cameraNode.Transform.Translation = new Vector3(0, 5, 10);
// Aim the camera toward the scene origin by rotating around the X axis
cameraNode.Transform.EulerAngles = new Vector3(-30, 0, 0);
```

For orthographic rendering, set `ProjectionType.Orthographic` and specify `OrthoHeight`.

---

### Adding Lights

Scenes without lights render completely dark. Add at least one `Light` to illuminate the geometry:

```csharp
using Aspose.ThreeD.Entities;

// Directional (sun-like) light
var sunLight = new Light("sun");
sunLight.LightType = LightType.Directional;
sunLight.Color = new Vector3(1.0, 1.0, 0.95); // slightly warm white
Node sunNode = scene.RootNode.CreateChildNode("sun", sunLight);
sunNode.Transform.EulerAngles = new Vector3(45, -30, 0); // direction in degrees

// Point light
var pointLight = new Light("fill");
pointLight.LightType = LightType.Point;
pointLight.Intensity = 150.0;
Node pointNode = scene.RootNode.CreateChildNode("fill_light", pointLight);
pointNode.Transform.Translation = new Vector3(-3, 4, 3);
```

---

### Rendering to an Image File

Use `Scene.Render` with `ImageRenderOptions` to produce a PNG, JPEG, or BMP image:

```csharp
using Aspose.ThreeD;
using Aspose.ThreeD.Utilities;

// Render to a PNG file at 1280x720 — size is Vector2, format is a string
scene.Render(camera, "output.png", new Vector2(1280, 720), "png");
```

> **Tip:** For production use, ensure at least one directional or ambient light is present. An unlit scene renders as a silhouette or solid black surface depending on the material.

---

### API Quick Reference

| Member | Description |
|---|---|
| `new Camera(projectionType)` | Create a camera; use `ProjectionType.Perspective` or `Orthographic` |
| `camera.FieldOfViewY` | Vertical field of view in degrees (perspective only) |
| `camera.NearPlane` | Near clipping plane distance |
| `camera.FarPlane` | Far clipping plane distance |
| `new Light(name)` | Create a light source |
| `light.LightType` | `Directional`, `Point`, or `Spot` |
| `light.Intensity` | Light intensity (positive float) |
| `light.Color` | RGB colour as `Vector3` |
| `new ImageRenderOptions()` | Render output configuration (background colour, shadows) |
| `scene.Render(camera, path, size, format)` | Render scene from camera viewpoint; `size` is `Vector2`, `format` is `"png"`, `"jpg"`, etc. |

## See Also

- [Aspose.3D for .NET — Enterprise Documentation](https://docs.aspose.com/3d/net/)
- [Working with Materials and Shading](materials-shading) — PBR and Phong materials affect render output
