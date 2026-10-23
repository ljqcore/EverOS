# Manual Memory Candidate Implementation Plan

## Goal

Enable a user to add a memory from the Candidate Review page, review it in the existing queue, and publish it through the existing EverOS confirmation flow.

## Scope

- Support the currently active review types: Episode (情节) and Preference (偏好).
- Collect memory type, project namespace, validity period, external-use policy, and content.
- Persist creation time and mark the candidate and resulting library record as manually authored.
- Manual candidates have no archived source evidence and do not require source validation.
- Do not change unrelated screens, extraction prompts, or existing import evidence behavior.

## Design Decisions

- Create a pending candidate and leave publication to the existing per-candidate confirmation action.
- Reuse the existing `candidates` table and create a small internal `manual` batch row because `candidates.batch_id` is required and the publish scope currently comes from its batch. The row is explicitly marked `source_type='manual'`, has no archive path, and is never presented as an imported file.
- Store `origin='manual'` and `evidence_kind='human_authored'`; represent its evidence status as `not_required`.
- Preference maps to EverOS `atomic_fact`. Episode metadata gets a generated title (`人工新增`) and the candidate-creation timestamp required by EverOS.
- Start validity when the memory is confirmed, using the existing `validity_days` behavior.

## Tasks

1. [x] Add a manual-candidate request and endpoint that validates project and fields, saves a pending candidate plus internal manual anchor, and returns the review item.
2. [x] Update candidate listing and confirmation so manual candidates need no source archive, are marked human-authored, and still publish through EverOS.
3. [x] Enable the Candidate Review form, add manual-origin/evidence presentation and filtering, create/select the candidate, and retain the existing review controls.
4. [x] Review the changed flow and run non-test static verification/build commands only. Do not add or run tests.

## Review Focus

- Manual candidates must not be mislabeled as having original-file evidence.
- Empty content, unsupported type, and nonexistent namespace must be rejected.
- Confirmation must persist `origin='manual'` and `evidence_kind='human_authored'` in both candidate and library metadata.
- Episode publication must satisfy EverOS's required title and timestamp metadata.
- Existing import candidates must keep their prior evidence validation and review behavior.
