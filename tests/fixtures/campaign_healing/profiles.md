---
page_role: howto_article
title: Working with Profiles
description: >-
  Create 2D cross-section profiles for sweep and extrusion operations in
  Aspose.3D for .NET — using parameterized shapes, arbitrary polygons,
  mirrored profiles, and centerline profiles.
type: docs
weight: 70
evidence:
  model_sha: 70933ab13eb0e313d9b160c55845011d366b1599
  model_version: 1.0.0
  claims:
  - CLM-3d-00fbda
  - CLM-3d-12a6c2
  - CLM-3d-1c0674
  - CLM-3d-2c0310
  - CLM-3d-4e1849
  - CLM-3d-4e6301
  - CLM-3d-a2e9c4
  - CLM-3d-bf1923
  - CLM-3d-d2bbcc
  - CLM-3d-d5d4fb
  - CLM-3d-de25d7
  - ERC-3d-net-214f7df6
  apis:
  - ArbitraryProfile
  - CenterLineProfile
  - CircleShape
  - Curve
  - FileFormat.GLTF2
  - LShape
  - LShape.Depth
  - LShape.Thickness
  - LShape.Width
  - LinearExtrusion
  - LinearExtrusion.Slices
  - MirroredProfile
  - ParameterizedProfile
  - Profile
  - RectangleShape
  - RectangleShape.XDim
  - RectangleShape.YDim
  - RevolvedAreaSolid
  - Scene
  - Scene.RootNode
  - Scene.Save
  - Shape
  - TShape
  formats:
  - ext: gltf
    support: both
  sections:
  - heading: Working with Profiles
    line: 66
    claims: []
    apis:
    - LinearExtrusion
    - RevolvedAreaSolid
  - heading: Parameterized Profiles
    line: 72
    claims:
    - CLM-3d-00fbda
    - CLM-3d-12a6c2
    - CLM-3d-4e6301
    - CLM-3d-d5d4fb
    - CLM-3d-de25d7
    - ERC-3d-net-214f7df6
    apis:
    - CircleShape
    - FileFormat.GLTF2
    - LShape
    - LinearExtrusion
    - LinearExtrusion.Slices
    - ParameterizedProfile
    - RectangleShape
    - RectangleShape.XDim
    - RectangleShape.YDim
    - Scene
    - Scene.RootNode
    - Scene.Save
    - TShape
    formats:
    - ext: gltf
      support: both
  - heading: Parameterized L-shaped Profiles
    line: 107
    claims:
    - CLM-3d-1c0674
    - CLM-3d-4e1849
    - CLM-3d-4e6301
    - CLM-3d-a2e9c4
    apis:
    - LShape
    - LShape.Depth
    - LShape.Thickness
    - LShape.Width
    - LinearExtrusion
    - Scene.RootNode
  - heading: Mirrored Profiles
    line: 126
    claims:
    - CLM-3d-12a6c2
    - CLM-3d-4e6301
    - CLM-3d-de25d7
    apis:
    - LinearExtrusion
    - MirroredProfile
    - Profile
    - RectangleShape
    - RectangleShape.XDim
    - RectangleShape.YDim
    - Scene.RootNode
  - heading: Centerline Profiles
    line: 147
    claims:
    - CLM-3d-4e6301
    apis:
    - CenterLineProfile
    - Curve
    - LinearExtrusion
    - Scene.RootNode
  - heading: API Quick Reference
    line: 163
    claims: []
    apis:
    - Shape
provenance:
  content_origin: skill-generated
  last_mechanism: skill
  auto_updatable: true
  content_hash: c3495d5e329af5d0d13e18b711293ca1
  content_created_at: '2026-07-12T00:00:00+00:00'
grade: B
graded_content_hash: "c3495d5e329af5d0d13e18b711293ca1"
grade_reasons:
  - "4 WARN finding(s) [audit] -> base grade B"
---

## Working with Profiles

Profiles in Aspose.3D for .NET define 2D cross-section shapes used as inputs to extrusion and solid revolution operations. `LinearExtrusion` sweeps a profile along a path and `RevolvedAreaSolid` revolves it around an axis.

---

### Parameterized Profiles

`ParameterizedProfile` provides standard geometric shapes — rectangle, circle, ellipse, trapezoid, and others — defined by numeric parameters rather than explicit polygon vertices.

```csharp
using Aspose.ThreeD;
using Aspose.ThreeD.Entities;
using Aspose.ThreeD.Profiles;

var scene = new Scene();

// Rectangle profile: 2 units wide, 1 unit tall
var rectProfile = new RectangleShape();
rectProfile.XDim = 2.0;
rectProfile.YDim = 1.0;

// Extrude the rectangle 5 units along Z
var extrusion = new LinearExtrusion(rectProfile, 5.0);
extrusion.Slices = 10;
scene.RootNode.CreateChildNode("beam", extrusion);

scene.Save("beam.gltf", FileFormat.GLTF2);
```

Other shapes in `ParameterizedProfile`:

| Class | Parameters |
|---|---|
| `RectangleShape` | `XDim`, `YDim`, `RoundingRadius` |
| `CircleShape` | `Radius` |
| `LShape` | `Width`, `Depth`, `Thickness`, `FilletRadius` |
| `TShape` | `Depth`, `FlangeWidth`, `WebThickness`, `FlangeThickness` |

---

### Parameterized L-shaped Profiles

`LShape` is a parameterized profile that produces an L-section structural beam from dimensional properties:

```csharp
using Aspose.ThreeD.Profiles;

// L-shaped cross-section structural beam
var lProfile = new LShape();
lProfile.Width     = 0.1;
lProfile.Depth     = 0.2;
lProfile.Thickness = 0.01;

var extrusion = new LinearExtrusion(lProfile, 4.0);
scene.RootNode.CreateChildNode("l_beam", extrusion);
```

---

### Mirrored Profiles

`MirroredProfile` creates a symmetric cross-section by mirroring a base profile. Pass any `Profile` instance to the constructor; the library generates the mirrored shape automatically.

```csharp
using Aspose.ThreeD.Profiles;

// Base profile to mirror
var baseProfile = new RectangleShape();
baseProfile.XDim = 0.5;
baseProfile.YDim = 1.0;

// Mirror the base profile to get a symmetric shape
var mirrored = new MirroredProfile(baseProfile);

var extrusion = new LinearExtrusion(mirrored, 3.0);
scene.RootNode.CreateChildNode("symmetric_beam", extrusion);
```

---

### Centerline Profiles

`CenterLineProfile` wraps a `Curve` and a wall thickness to produce a hollow cross-section (e.g., a tube wall). Pass the centerline curve and thickness to the constructor.

```csharp
using Aspose.ThreeD.Profiles;
using Aspose.ThreeD.Entities;

var circle = new Circle { Radius = 0.5 };
var tube = new CenterLineProfile(circle, 0.05); // 5 cm wall
var extrusion = new LinearExtrusion(tube, 10.0);
scene.RootNode.CreateChildNode("pipe", extrusion);
```

---

### API Quick Reference

| Member | Description |
|---|---|
| `new RectangleShape()` | Rectangular parameterized profile (`XDim`, `YDim`, `RoundingRadius`) |
| `new CircleShape()` | Circular parameterized profile (`Radius`) |
| `new LShape()` | L-shaped structural beam profile |
| `new TShape()` | T-shaped structural beam profile |
| `new MirroredProfile(base)` | Symmetric profile mirrored from a base profile |
| `new CenterLineProfile(curve, thickness)` | Hollow profile with given wall thickness |
| `new LinearExtrusion(profile, height)` | Sweep a profile along the Z axis |
| `extrusion.Slices` | Number of subdivision segments along the sweep |
| `new RevolvedAreaSolid()` | Revolve a profile around an axis; set `Shape` and `AngleEnd` properties |

## See Also

- [Aspose.3D for .NET — Enterprise Documentation](https://docs.aspose.com/3d/net/)
- [Working with Scene Entities](scene-entities) — attach extruded solids to scene nodes
