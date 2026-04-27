---
title: "Preservacion de Estructura"
description: "Una pagina con shortcode, tabla, bloque de codigo y enlaces"
draft: false
weight: 1
---

# Preservacion de Estructura

{{< notice info >}}
Este bloque shortcode debe sobrevivir una compilacion Hugo.
{{< /notice >}}

| Caracteristica | Esperado |
| --- | --- |
| Shortcode | Renderizado |
| Tabla | Analizada |
| Codigo | Resaltado |

```python
def greet(name: str) -> str:
    return f"Hello, {name}"
```

Lee la [pagina inicial]({{< relref "/" >}}).

