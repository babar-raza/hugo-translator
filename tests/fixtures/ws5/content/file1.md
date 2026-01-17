---
title: "WS5 Test File 1 - Large Content for OOM Testing"
description: "This file contains substantial content to trigger OOM at high batch sizes"
---

# WS5 Integration Test - File 1 (Large)

This test file is designed to trigger Out-of-Memory errors when processed with excessively high batch sizes (e.g., batch_size=100). The OOM retry handler should engage, reduce the batch size exponentially (100→50→25), and eventually succeed.

## Test Scenario

**Purpose**: Validate WS1 (OOM Handler Fix) + WS2 (Callback Integration)

**Expected Behavior**:
1. First attempt at batch_size=100 → OOM
2. Retry at batch_size=50 → OOM
3. Retry at batch_size=25 → SUCCESS
4. Learning callback invoked: `OOM RECOVERY: 100→25, teaching adaptive tracker`
5. Next file (file2.md) starts with batch_size=25

## Content for Translation

The following content is repeated multiple times to create a large enough batch that will exhaust GPU memory at high batch sizes.

### Section 1: Introduction

Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.

Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.

### Section 2: Technical Details

The autonomous recovery system consists of three integrated components: the OOM retry handler, the adaptive batch stats tracker, and the hardware-aware GPU optimizer. These systems work together to provide robust, self-healing translation capabilities.

When a CUDA Out-of-Memory error occurs during translation, the retry handler catches the exception, reduces the batch size by 50%, clears the GPU cache, and attempts the translation again. This process repeats up to 3 times (configurable) until either success or the minimum batch size is reached.

### Section 3: Implementation

The callback mechanism (WS2) enables the retry handler to teach the adaptive batch tracker when OOM recovery succeeds. This cross-system learning prevents future OOM errors on similar files by permanently reducing the batch size for the affected language.

The hardware baseline integration (WS3) ensures that new languages start with GPU-calculated safe batch sizes rather than hardcoded defaults. This reduces the likelihood of initial OOM errors and speeds up convergence to optimal batch sizes.

### Section 4: Observability

Enhanced logging (WS4) makes all autonomous systems visible through:
- Startup diagnostics showing which systems are enabled with their parameters
- Per-file protection status logs before each translation
- Detailed OOM retry logs with batch size reduction sequence
- Log file validation to catch silent failures early

### Section 5: Additional Content

This section contains additional paragraphs to increase the file size further. The goal is to create enough translation units that batch_size=100 will definitely exceed GPU memory, forcing the OOM retry handler to engage.

When translating markdown files, the system first extracts text units, then processes them in batches. Each batch is sent to the transformer model for translation. Large batch sizes improve throughput but risk OOM errors if the combined size exceeds GPU memory.

The optimal batch size depends on multiple factors: GPU memory capacity, model size, text complexity, and target language script characteristics. For example, languages with complex scripts (e.g., Arabic, Japanese) typically require smaller batch sizes due to longer token sequences.

### Section 6: Test Expectations

After this file is translated with batch_size=100 (forced OOM), we expect:

1. **Logs show retry attempts**:
   ```
   OOM on file1.md (attempt 1/3), retrying with batch_size=50
   OOM on file1.md (attempt 2/3), retrying with batch_size=25
   ```

2. **Recovery callback invoked**:
   ```
   OOM RECOVERY: 100→25, teaching adaptive tracker
   ```

3. **batch_stats.json updated**:
   ```json
   {
     "languages": {
       "es": {
         "batch_size": 25,
         "current_batch_size": 25,
         "fallback_count": 1
       }
     }
   }
   ```

4. **Subsequent files use learned batch size**:
   ```
   Translating file2.md | OOM Protection: ACTIVE (max_retries=3) | Batch size: 25
   ```

### Section 7: Verification

To verify this test scenario, examine the logs for:
- OOM pattern matching: `OOM pattern matched: 'cuda out of memory'`
- Batch reduction sequence: Logs showing 100→50→25
- Success after retry: Translation completes successfully
- Learning applied: Next file starts with batch_size=25

### Section 8: Edge Cases

The system should handle edge cases gracefully:
- Multiple consecutive OOM errors (retry up to max_retries)
- Minimum batch size reached (final attempt with batch_size=1)
- Non-OOM exceptions (should not trigger retry, fail immediately)
- Disabled retry handler (should show helpful error message)

### Section 9: Performance Impact

The OOM retry mechanism adds minimal overhead when not triggered:
- No performance impact during normal operation
- Retry delay only occurs when OOM happens
- Aggressive GPU cache clearing between retries
- Learning prevents repeated OOM on subsequent files

### Section 10: Conclusion

This test file validates the complete autonomous recovery pipeline: OOM detection, exponential retry, cross-system learning, and observable diagnostics. Success means the system can handle GPU memory constraints autonomously without manual intervention.

---

**End of Test File 1**

Note: This content is intentionally verbose to trigger OOM at high batch sizes. In production, typical markdown files are much smaller and won't trigger OOM under normal batch size settings.
