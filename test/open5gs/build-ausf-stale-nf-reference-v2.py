#!/usr/bin/env python3
"""Build a separate patched AUSF image without changing upstream sources."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


REVISION = "6d91a793af25ee36dc4662755843192177ee412b"
IMAGE = "limx59/open5gs-ausf:arm64-stale-nf-reference-test"
INPUTS = (
    "meson.build", "meson_options.txt", "LICENSE",
    "configs", "lib", "src", "misc", "tests", "subprojects",
)
PATCHED = (
    "src/ausf/sbi-path.h",
    "src/ausf/sbi-path.c",
    "src/ausf/ausf-sm.c",
)


def output(args, cwd=None):
    return subprocess.check_output(
        args, cwd=cwd, text=True, timeout=30,
    ).strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / "open5gs"
    require(source.resolve().is_relative_to(root.resolve()),
            "Source must remain inside review repository")
    patch = root / "test/open5gs/patches/patch-ausf-stale-nf-reference.py"
    dockerfile = root / "docker/open5gs/Dockerfile.ausf-stale-nf-reference"

    require(output(["git", "rev-parse", "HEAD"], source) == REVISION,
            "Unexpected Open5GS source revision")
    require(not output(
        ["git", "status", "--porcelain", "--", *PATCHED], source),
        "Reviewed upstream files have local changes")

    before = {name: sha(source / name) for name in PATCHED}
    base = json.loads(output([
        "sudo", "docker", "image", "inspect", "docker_open5gs:local-arm64",
    ]))[0]
    require(base["Architecture"] == "arm64", "Runtime image is not ARM64")
    require(base["Id"] == "sha256:69d576e04d6e5a094b8c0e37e69bc1ba173dfa23bbfaf4de712f5959b5f04edd",
            "Unexpected original runtime image")

    parent = root / "test/open5gs/.local/evidence"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="ausf-stale-nf-build-", dir=parent))
    dest.chmod(0o700)
    print("Build evidence:", dest, flush=True)

    metadata = {
        "built": False,
        "authentication_recovery_validated": False,
        "source_revision": REVISION,
        "patch_sha256": sha(patch),
        "dockerfile_sha256": sha(dockerfile),
        "runtime_image_id": base["Id"],
        "image": IMAGE,
        "build_jobs": 2,
    }
    try:
        archive = dest / "source.tar"
        with archive.open("xb") as stream:
            subprocess.run(
                ["git", "archive", "--format=tar", REVISION, *INPUTS],
                cwd=source, stdout=stream, check=True, timeout=120,
            )
        metadata["source_archive_sha256"] = sha(archive)

        # Preserve the exact local runtime image under a separate build tag.
        base_tag = "oai-pi-open5gs:ausf-runtime-base-" + base["Id"].split(":")[1][:12]
        subprocess.run(
            ["sudo", "docker", "image", "tag", base["Id"], base_tag],
            check=True, timeout=30,
        )

        with tempfile.TemporaryDirectory(prefix="ausf-source-build-", dir=dest) as temporary:
            snapshot = Path(temporary)
            subprocess.run([
                "tar", "--no-same-owner", "-xf", str(archive),
                "-C", str(snapshot),
            ], check=True, timeout=120)

            subprocess.run([
                "python3", "-B", str(patch),
                "--source-root", str(snapshot),
            ], check=True, timeout=30)

            subprocess.run([
                "sudo", "docker", "build",
                "--build-arg", "BUILD_JOBS=2",
                "--build-arg", "OPEN5GS_RUNTIME_IMAGE=" + base_tag,
                "--build-context", "open5gs_source=" + str(snapshot),
                "--iidfile", str(dest / "image-id.txt"),
                "-f", str(dockerfile),
                "-t", IMAGE,
                str(root),
            ], check=True, timeout=7200)

        metadata["image_id"] = (dest / "image-id.txt").read_text().strip()
        metadata["built"] = True
    except Exception as error:
        metadata["error"] = str(error)
        raise
    finally:
        metadata["original_source_unchanged"] = all(
            sha(source / name) == before[name] for name in PATCHED
        )
        (dest / "summary.json").write_text(
            json.dumps(metadata, indent=2) + "\n"
        )
        print("Evidence retained:", dest, flush=True)

    require(metadata["original_source_unchanged"], "Original source changed")
    print("BUILT:", IMAGE)
    print("Original source unchanged; running AUSF was not replaced.")
    print("Authentication and abnormal-recovery acceptance remain pending.")


if __name__ == "__main__":
    main()
