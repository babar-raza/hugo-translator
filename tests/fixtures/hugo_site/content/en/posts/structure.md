---
title: "Structure Preservation"
description: "A page with shortcode, table, code block, and links"
draft: false
weight: 1
---

# Structure Preservation

{{< notice info >}}
This shortcode block must survive a Hugo build.
{{< /notice >}}

| Feature | Expected |
| --- | --- |
| Shortcode | Rendered |
| Table | Parsed |
| Code | Highlighted |

```python
def greet(name: str) -> str:
    return f"Hello, {name}"
```

Read the [home page]({{< relref "/" >}}).

