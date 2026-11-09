# Separate formatting-only review

This baseline is independent from the CI implementation and the earlier uncommitted Phase 3 work.
No commit or staging has been performed. `formatting-baseline.patch` contains **only** the existing
baseline's Ruff edits and `.gitattributes` LF checkout policy; it contains no CI or business changes.
All 11 files were clean before formatting, and their Python ASTs were identical before/after.

Files formatted:
- `infra/local/verify_upload.py`
- `src/event_driven_document_processor/bootstrap/aws.py`
- `src/event_driven_document_processor/bootstrap/dependencies.py`
- `src/event_driven_document_processor/bootstrap/routes.py`
- `src/event_driven_document_processor/main.py`
- `src/event_driven_document_processor/modules/documents/api/router.py`
- `src/event_driven_document_processor/modules/documents/application/ports.py`
- `src/event_driven_document_processor/modules/documents/infrastructure/s3_upload_authorizer.py`
- `tests/unit/test_dynamodb_repository.py`
- `tests/unit/test_s3_authorizer.py`
- `tests/unit/test_uploads.py`

`routes.py` needed only a missing final newline; it has no semantic edits. All eleven Python files
appear in the patch. `.gitattributes` (`*.py text eol=lf`) also makes Python checkout line endings
consistent on Windows. This is a whitespace policy, not a Ruff exclusion or weakened check.

Review the standalone patch. When **you** choose to stage it separately from CI/Phase 3:

```sh
git apply --cached --check docs/changes/formatting-baseline.patch
git apply --cached docs/changes/formatting-baseline.patch
git diff --cached --stat
git diff --cached
```

The patch is already applied to the working tree: do not apply it there again. The `--cached`
commands above are user-operated instructions, not actions taken by the agent. They stage only
the formatting patch; do not use `git add .` to combine unrelated work. The patch/this review note
can be kept as review artifacts or included with CI documentation, outside the formatting change.
