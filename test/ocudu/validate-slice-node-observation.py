#!/usr/bin/env python3
"""Check queue observation rules and replay retained dual-node logs."""
import argparse
import json
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[2]
observe = runpy.run_path(str(
    Path(__file__).with_name("slice_node_observation.py")
))["observe"]
EMPTY = {"stdout": "", "stderr": ""}
LINE = (
    "- UE PDSCH: ue=0 c-rnti=0x4601 h_id=1 rb=[0..10) "
    "symb=[2..10) cw[0]: tbs=88 mcs=3 rv=0 nrtx=0 "
    "k1=6 dl_bo=9 olla=0.027 grants: lcid=4: size=86\n"
)


def sample(before=None, after=None):
    return observe(
        "420", "test-source", 1,
        EMPTY if before is None else before,
        {"stdout": LINE, "stderr": ""} if after is None else after,
        1.0, 2.0,
    )


class ObservationChecks(unittest.TestCase):
    def test_post_grant_bytes_preserved(self):
        result = sample()
        self.assertEqual(result["queue_unit"], "bytes")
        self.assertEqual(result["samples"][0]["pending_dl_bytes_after_grant"], 9)
        self.assertEqual(result["samples"][0]["prb_width"], 10)
        self.assertFalse(result["prb_demand_percent_established"])

    def test_no_new_grant_is_unknown(self):
        before = {"stdout": LINE, "stderr": ""}
        result = sample(before, dict(before))
        self.assertEqual(result["observation_status"], "unknown")
        self.assertIsNone(result["queue_statistics"])

    def test_only_new_records_counted(self):
        before = {"stdout": LINE, "stderr": ""}
        after = {"stdout": LINE + LINE.replace("dl_bo=9", "dl_bo=0"),
                 "stderr": ""}
        result = sample(before, after)
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["queue_statistics"]["maximum"], 0)

    def test_zero_queue_is_observed_not_missing(self):
        result = sample(after={
            "stdout": LINE.replace("dl_bo=9", "dl_bo=0"), "stderr": "",
        })
        self.assertEqual(result["observation_status"], "observed")
        self.assertEqual(result["queue_statistics"]["positive_samples"], 0)

    def test_history_replacement_rejected(self):
        with self.assertRaisesRegex(ValueError, "history changed"):
            sample({"stdout": LINE, "stderr": ""}, EMPTY)

    def test_partial_line_rejected(self):
        with self.assertRaisesRegex(ValueError, "partial line"):
            sample(after={"stdout": LINE.rstrip("\n"), "stderr": ""})

    def test_unknown_identity_channel_or_retransmission_rejected(self):
        for old, new, reason in (
            ("ue=0 ", "ue=1 ", "Unexpected UE identity"),
            ("lcid=4:", "lcid=5:", "logical channel"),
            ("nrtx=0", "nrtx=1", "Retransmission"),
        ):
            with self.subTest(new=new):
                with self.assertRaisesRegex(ValueError, reason):
                    sample(after={"stdout": LINE.replace(old, new), "stderr": ""})

    def test_missing_queue_field_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unparsed"):
            sample(after={
                "stdout": LINE.replace("dl_bo=9 ", ""), "stderr": "",
            })


def replay(dest):
    dest = dest.resolve()
    if not dest.is_relative_to(
        (ROOT / "test/ocudu/.local/evidence").resolve()
    ) or not dest.is_dir():
        raise RuntimeError("Unexpected retained evidence directory")

    def read(name):
        path = dest / name
        if not path.resolve().is_relative_to(dest) or not path.is_file():
            raise RuntimeError("Missing or unexpected retained evidence")
        return json.loads(path.read_text())

    summary = read("summary.json")
    if summary.get("passed") is not True:
        raise RuntimeError("Original run did not pass")
    results = []
    for revision, phase in enumerate(summary["phases"], 1):
        for node, service in (("420", "gnb"), ("421", "gnb-2")):
            label = phase["label"]
            source = summary["test_before"][service]
            result = observe(
                node, source["id"] + ":" + source["started"], revision,
                read(f"gnb.{label}.{node}.before.json"),
                read(f"gnb.{label}.{node}.after.json"),
                # Offline ordering fixtures; actual query times were not saved.
                float(revision * 2), float(revision * 2 + 1),
            )
            results.append({
                "phase": label,
                "node": node,
                "sample_count": result["sample_count"],
                "observation_status": result["observation_status"],
                "queue_statistics": result["queue_statistics"],
                "host_query_times_are_replay_fixtures": True,
                "source_collection_time_validated": False,
            })
    print(json.dumps({
        "scope": "Retained log parsing only",
        "results": results,
        "live_reporting_validated": False,
    }, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ObservationChecks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    if args.evidence:
        replay(args.evidence)
    print("PASS: observation checks; no containers or control requests started.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
