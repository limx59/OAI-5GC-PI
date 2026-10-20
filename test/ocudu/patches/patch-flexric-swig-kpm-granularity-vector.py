#!/usr/bin/env python3
"""Expose the KPM optional granularity vector through SWIG."""

import argparse
from pathlib import Path


def transform(text):
    old = "  %template(IntVector) vector<int>;"
    new = old + (
        "\n  %template(KPM_GranularityVector) vector<unsigned long>;"
    )
    if "KPM_GranularityVector" in text:
        raise SystemExit("STOP: granularity vector binding already present")
    if text.count(old) != 1:
        raise SystemExit("STOP: unexpected vector-template anchor")
    text = text.replace(old, new, 1)
    generic = "%typemap(out) std::vector<long unsigned int> * {"
    scoped = "%typemap(out) std::vector<long unsigned int> *cu_du_id {"
    if text.count(generic) != 1:
        raise SystemExit("STOP: unexpected generic CU/DU vector typemap")
    text = text.replace(generic, scoped, 1)
    anchor = "/* intXX_t mapping: C -> Python */"
    override = r"""// Keep granularity numeric despite the generic CU/DU string typemap.
%typemap(out) std::vector<unsigned long> *gran_period_ms {
    Py_ssize_t count = $1 == NULL ? 0 : (Py_ssize_t)$1->size();
    $result = PyList_New(count);
    if ($result == NULL) {
        SWIG_fail;
    }
    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject* item = PyLong_FromUnsignedLong((*$1)[i]);
        if (item == NULL) {
            Py_DECREF($result);
            $result = NULL;
            SWIG_fail;
        }
        PyList_SET_ITEM($result, i, item);
    }
}

"""
    if text.count(anchor) != 1:
        raise SystemExit("STOP: unexpected Python typemap anchor")
    return text.replace(anchor, override + anchor, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    if not args.check and any(
        (parent / ".git").exists() for parent in (root, *root.parents)
    ):
        raise SystemExit("STOP: apply only outside a Git working tree")
    path = root / "src/xApp/swig/swig_wrapper.i"
    updated = transform(path.read_text())
    if not args.check:
        path.write_text(updated)
    print(f"{'CHECK' if args.check else 'PATCH'}: src/xApp/swig/swig_wrapper.i")
    print("SWIG granularity binding only; build and offline validation pending.")


if __name__ == "__main__":
    main()
