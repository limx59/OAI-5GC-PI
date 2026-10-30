#!/usr/bin/env python3
"""Invalidate stale AUSF NF references in a disposable Open5GS build tree."""

import argparse
from pathlib import Path


MARKER = "AUSF_STALE_NF_REFERENCE_GUARD"

HELPER = """
/* AUSF_STALE_NF_REFERENCE_GUARD
 * Compare cached pointers with live objects before dereferencing them.
 * Run on the AUSF event-loop thread, before an object-pool slot is reused.
 */
void ausf_sbi_invalidate_stale_nf_references(void)
{
    ausf_ue_t *ue = NULL;
    ogs_sbi_nf_instance_t *live = NULL;
    unsigned int cleared = 0;
    size_t group, i, count;

    ogs_list_for_each(&ausf_self()->ausf_ue_list, ue) {
        for (group = 0; group < 2; group++) {
            count = group == 0 ?
                sizeof(ue->sbi.nf_type_array) /
                    sizeof(ue->sbi.nf_type_array[0]) :
                sizeof(ue->sbi.service_type_array) /
                    sizeof(ue->sbi.service_type_array[0]);

            for (i = 0; i < count; i++) {
                ogs_sbi_nf_instance_t **cached = group == 0 ?
                    &ue->sbi.nf_type_array[i].nf_instance :
                    &ue->sbi.service_type_array[i].nf_instance;
                ogs_time_t *timeout = group == 0 ?
                    &ue->sbi.nf_type_array[i].validity_timeout :
                    &ue->sbi.service_type_array[i].validity_timeout;
                bool found = false;

                if (!*cached)
                    continue;

                ogs_list_for_each(
                        &ogs_sbi_self()->nf_instance_list, live) {
                    if (live == *cached) {
                        found = true;
                        break;
                    }
                }

                if (!found) {
                    *cached = NULL;
                    *timeout = 0;
                    cleared++;
                }
            }
        }
    }

    if (cleared)
        ogs_warn("AUSF cleared stale NF references [%u]", cleared);
}

"""


def once(text, old, new, name):
    if text.count(old) != 1:
        raise RuntimeError(f"Unexpected patch anchor in {name}: {old[:80]!r}")
    return text.replace(old, new, 1)


def prepare(root):
    names = (
        "src/ausf/sbi-path.h",
        "src/ausf/sbi-path.c",
        "src/ausf/ausf-sm.c",
    )
    originals = {name: (root / name).read_text() for name in names}
    marked = [MARKER in originals[name] for name in names]
    if any(marked):
        raise RuntimeError(
            "Patch markers already present; use a fresh source copy "
            "rather than applying twice or accepting a partial patch"
        )

    updates = dict(originals)
    name = names[0]
    updates[name] = once(
        updates[name],
        "void ausf_sbi_close(void);\n",
        "void ausf_sbi_close(void);\n\n"
        "/* AUSF_STALE_NF_REFERENCE_GUARD */\n"
        "void ausf_sbi_invalidate_stale_nf_references(void);\n",
        name,
    )

    name = names[1]
    updates[name] = once(
        updates[name],
        "int ausf_sbi_discover_and_send(\n",
        HELPER + "int ausf_sbi_discover_and_send(\n",
        name,
    )
    updates[name] = once(
        updates[name],
        "    xact = ogs_sbi_xact_add(\n",
        "    ausf_sbi_invalidate_stale_nf_references();\n\n"
        "    xact = ogs_sbi_xact_add(\n",
        name,
    )

    name = names[2]
    updates[name] = once(
        updates[name],
        "    switch (e->h.id) {\n",
        "    /* AUSF_STALE_NF_REFERENCE_GUARD */\n"
        "    ausf_sbi_invalidate_stale_nf_references();\n\n"
        "    switch (e->h.id) {\n",
        name,
    )
    updates[name] = once(
        updates[name],
        "                    ogs_nnrf_nfm_handle_nf_status_notify(stream, &message);\n",
        "                    ogs_nnrf_nfm_handle_nf_status_notify(stream, &message);\n"
        "                    ausf_sbi_invalidate_stale_nf_references();\n",
        name,
    )
    # Peer NF removal can also occur during NF FSM dispatch.
    import re
    name = names[2]
    pattern = re.compile(
        r"(?m)^([ \t]*)ogs_fsm_dispatch\(&nf_instance->sm, e\);$"
    )
    if len(list(pattern.finditer(updates[name]))) != 2:
        raise RuntimeError("Expected two AUSF NF FSM dispatch sites")
    updates[name] = pattern.sub(
        lambda match: (
            match.group(0) + "\n" + match.group(1)
            + "ausf_sbi_invalidate_stale_nf_references();"
        ),
        updates[name],
    )
    return updates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply only inside a disposable build-source copy",
    )
    args = parser.parse_args()
    updates = prepare(args.source_root.resolve())

    for name in updates:
        print("CHECKED:", name)
    if args.apply:
        for name, text in updates.items():
            (args.source_root / name).write_text(text)
        print("APPLIED: AUSF stale NF reference guard")
    else:
        print("PASS: patch anchors; no source files changed")


if __name__ == "__main__":
    main()
