# KPM delete rejection source snapshots

Original and patched files are review material. Docker builds apply the Python patch scripts to isolated source copies.

See manifest.json for patch order and SHA-256 checksums. FlexRIC snapshots cover codec changes only; the complete runtime patch order is in Dockerfile.flexric-delete-rejection.

OCUDU fault injection requires OAI_PI_TEST_REJECT_FIRST_DELETE=1 and rejects the first existing-subscription delete per manager. It is test-only.

Three integration rounds passed rejection, continued reporting, retry and post-delete silence. Absent-subscription deletion, timeouts, duplicate messages and optional diagnostics remain untested.
