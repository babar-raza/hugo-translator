Close this task cleanly.

1. Review everything changed in this session.
2. Commit all completed changes. If the work spans clearly different change groups, use logically separated commits. Otherwise use one clean commit.
3. Update the master plan in place with the current final status. Amend it, do not overwrite history. Record:
   - what was completed
   - what changed
   - verification performed
   - any remaining follow-ups or non-blockers
4. Mark the task closed only if the implementation, verification, commit, and master plan update are all complete.
5. In the final response, provide:
   - files changed
   - commit hash(es)
   - exact master plan sections updated
   - closure status: CLOSED or NOT CLOSED

Rules:
- Do not claim closure without verifying the final repo state.
- Do not leave uncommitted relevant changes behind.
- Do not create ad hoc summary files unless required by governance.
- Prefer existing governed workflows and skills.
