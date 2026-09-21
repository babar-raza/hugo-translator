---
page_role: howto_article
title: Working with Deformers
description: >-
  Apply skeletal and morph-target deformations to meshes in Aspose.3D for .NET —
  binding bones to vertices with SkinDeformer, defining morph targets with
  MorphTargetDeformer, and controlling blend weights at runtime.
type: docs
weight: 110
evidence:
  model_sha: 70933ab13eb0e313d9b160c55845011d366b1599
  model_version: 1.0.0
  claims:
  - CLM-3d-0f653e
  - CLM-3d-1d6fc4
  - CLM-3d-4e6301
  - CLM-3d-752d43
  - CLM-3d-8235e9
  - CLM-3d-a27b03
  - CLM-3d-be726a
  - CLM-3d-d91e01
  - CLM-3d-dc060f
  - CLM-3d-df7572
  - CLM-3d-ed43f5
  - ERC-3d-net-1f5ea9d9
  - ERC-3d-net-214f7df6
  - ERC-3d-net-9890a844
  - ERC-3d-net-f30ec751
  apis:
  - Bone
  - Bone.BoneTransform
  - Bone.SetWeight
  - Deformer
  - Matrix4.Identity
  - Mesh
  - Mesh.Deformers
  - MorphTargetChannel
  - MorphTargetChannel.SetWeight
  - MorphTargetChannel.Targets
  - MorphTargetDeformer
  - MorphTargetDeformer.Channels
  - Scene
  - Scene.RootNode
  - Shape
  - SkinDeformer
  - SkinDeformer.Bones
  sections:
  - heading: Working with Deformers
    line: 119
    claims:
    - ERC-3d-net-1f5ea9d9
    - ERC-3d-net-9890a844
    - ERC-3d-net-f30ec751
    apis:
    - Bone
    - MorphTargetDeformer
    - SkinDeformer
  - heading: Skeletal Deformation with SkinDeformer
    line: 125
    claims:
    - CLM-3d-0f653e
    - CLM-3d-1d6fc4
    - CLM-3d-4e6301
    - CLM-3d-df7572
    - CLM-3d-ed43f5
    - ERC-3d-net-1f5ea9d9
    - ERC-3d-net-214f7df6
    - ERC-3d-net-f30ec751
    apis:
    - Bone
    - Bone.BoneTransform
    - Bone.SetWeight
    - Matrix4.Identity
    - Mesh
    - Mesh.Deformers
    - Scene
    - Scene.RootNode
    - SkinDeformer
    - SkinDeformer.Bones
  - heading: Morph Target Deformation
    line: 154
    claims:
    - CLM-3d-4e6301
    - CLM-3d-752d43
    - CLM-3d-8235e9
    - CLM-3d-a27b03
    - ERC-3d-net-214f7df6
    - ERC-3d-net-9890a844
    apis:
    - Mesh
    - Mesh.Deformers
    - MorphTargetChannel
    - MorphTargetChannel.SetWeight
    - MorphTargetChannel.Targets
    - MorphTargetDeformer
    - MorphTargetDeformer.Channels
    - Scene
    - Scene.RootNode
    - Shape
  - heading: API Quick Reference
    line: 185
    claims: []
    apis:
    - Shape
provenance:
  content_origin: skill-generated
  last_mechanism: manual-edit-skill
  auto_updatable: true
  content_hash: 71ecb326d01a27c6ea826bdc6efb7688
  content_created_at: '2026-07-12T00:00:00+00:00'
  reviewed: false
grade: A
graded_content_hash: "71ecb326d01a27c6ea826bdc6efb7688"
grade_reasons:
  - "No findings -> grade A"
---

## Working with Deformers

Aspose.3D for .NET supports two deformation systems: **skeletal deformation** via `SkinDeformer` and `Bone`, which bind a skeleton to a mesh for character animation, and **morph target deformation** via `MorphTargetDeformer`, which blends between multiple mesh shapes.

---

### Skeletal Deformation with SkinDeformer

A `SkinDeformer` attaches a set of `Bone` objects to a mesh. Each bone defines a weight for every vertex it influences. The mesh deforms when the bone transforms change.

```csharp
using Aspose.ThreeD;
using Aspose.ThreeD.Deformers;
using Aspose.ThreeD.Entities;

var scene = new Scene();
var mesh = new Mesh("body");
Node meshNode = scene.RootNode.CreateChildNode("body", mesh);

// Create a SkinDeformer and attach it to the mesh
var skin = new SkinDeformer();
mesh.Deformers.Add(skin);

// Define a bone and assign per-vertex weights
var bone = new Bone("spine");
bone.BoneTransform = Matrix4.Identity;
bone.SetWeight(0, 1.0);
bone.SetWeight(1, 0.8);
skin.Bones.Add(bone);
```

> Vertex indices passed to `SetWeight` must be valid indices in the mesh's control-points array. Weights are typically normalized so they sum to 1.0 across all bones influencing a vertex.

---

### Morph Target Deformation

`MorphTargetDeformer` blends the base mesh toward one or more target shapes. Each target is a separate mesh with the same topology but different vertex positions.

```csharp
using Aspose.ThreeD;
using Aspose.ThreeD.Deformers;
using Aspose.ThreeD.Entities;

var scene = new Scene();
var baseMesh = new Mesh("face_neutral");
scene.RootNode.CreateChildNode("face", baseMesh);

// Target shape
var smileMesh = new Shape("face_smile");

// Attach a MorphTargetDeformer
var morph = new MorphTargetDeformer();
baseMesh.Deformers.Add(morph);

// Add a morph channel targeting the smile mesh
var smileChannel = new MorphTargetChannel("smile");
smileChannel.Targets.Add(smileMesh);
morph.Channels.Add(smileChannel);

// At runtime, set the blend weight (0.0 = base, 1.0 = full target)
smileChannel.SetWeight(smileMesh, 0.75);
```

---

### API Quick Reference

| Member | Description |
|---|---|
| `new SkinDeformer()` | Create a skeletal deformer to attach to a mesh |
| `skin.Bones` | `IList<Bone>` of bones in this deformer |
| `new Bone(name)` | Create a named bone |
| `bone.SetWeight(vertexIndex, weight)` | Assign a blend weight to a vertex |
| `bone.BoneTransform` | Bind-pose offset matrix for this bone |
| `new MorphTargetDeformer()` | Create a morph target deformer |
| `morph.Channels` | `IList<MorphTargetChannel>` of blend channels |
| `new MorphTargetChannel(name)` | Create a named morph channel |
| `channel.ChannelWeight` | Blend weight: 0.0 = base, 1.0 = target |
| `channel.SetWeight(target, weight)` | Sets the blend weight for a target shape (`target`: `Shape`, `weight`: `double`) |
| `mesh.Deformers` | Collection of deformers on a mesh |

## See Also

- [Aspose.3D for .NET — Enterprise Documentation](https://docs.aspose.com/3d/net/)
- [Working with Scene Entities](scene-entities) — attach deformers to scene nodes
