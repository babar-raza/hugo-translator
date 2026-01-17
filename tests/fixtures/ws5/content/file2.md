---
title: "WS5 Test File 2 - Medium Content"
description: "Second test file to verify learning propagation"
---

# WS5 Integration Test - File 2 (Medium)

This is the second test file. It should benefit from the OOM learning that occurred during file1.md translation.

## Expected Behavior

Since file1.md triggered OOM and succeeded at batch_size=25, this file should:
1. Start with batch_size=25 (learned from file1)
2. Complete successfully without OOM
3. Demonstrate that learning propagates within the same translation run

## Test Content

### Introduction

This file contains moderate content - enough to translate meaningfully, but not enough to cause OOM at reasonable batch sizes like 25.

### Main Section

The autonomous recovery system successfully learned from the previous file's OOM experience. The adaptive batch tracker was taught (via the WS2 callback mechanism) that batch_size=100 fails but batch_size=25 succeeds for this language.

This learning is applied immediately within the same process, so file2.md benefits from file1.md's experience without needing to hit OOM itself.

### Verification

Check the logs for:
```
Translating file2.md | OOM Protection: ACTIVE (max_retries=3) | Batch size: 25
```

Notice: batch_size=25, NOT 100. This proves learning propagation.

### Conclusion

If this file translates successfully at batch_size=25 without any OOM errors, it validates that:
- The callback mechanism (WS2) works correctly
- The adaptive tracker updates batch_size immediately
- Learning propagates within the same run
- No manual intervention required

---

**End of Test File 2**
