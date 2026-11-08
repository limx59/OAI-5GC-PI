#!/usr/bin/env python3
"""Use an unambiguous advertised service port for an IPv4 UDR instance."""
import argparse
import difflib
from pathlib import Path


FUNCTION = """static ogs_sbi_client_t *nf_instance_find_client(
        ogs_sbi_nf_instance_t *nf_instance)
{
    ogs_sbi_client_t *client = NULL;
    ogs_sockaddr_t *addr = NULL, *addr6 = NULL;
"""

HELPER = """static uint16_t udr_instance_advertised_port(
        ogs_sbi_nf_instance_t *nf_instance,
        OpenAPI_uri_scheme_e scheme, ogs_sockaddr_t *addr)
{
    ogs_sbi_nf_service_t *service = NULL;
    char instance_address[OGS_ADDRSTRLEN];
    char service_address[OGS_ADDRSTRLEN];
    uint16_t port = 0;
    int i;

    OGS_ADDR(addr, instance_address);
    ogs_list_for_each(&nf_instance->nf_service_list, service) {
        if (service->scheme != scheme)
            continue;

        for (i = 0; i < service->num_of_addr; i++) {
            ogs_sockaddr_t *endpoint = service->addr[i].ipv4;
            uint16_t advertised_port;

            if (!endpoint ||
                strcmp(instance_address,
                    OGS_ADDR(endpoint, service_address)) != 0)
                continue;

            advertised_port = OGS_PORT(endpoint);
            if (!service->addr[i].is_port || !advertised_port ||
                (port && port != advertised_port))
                return 0;

            port = advertised_port;
        }
    }

    return port;
}

"""

ADDRESS_SELECTION = """    if (nf_instance->num_of_ipv4) addr = nf_instance->ipv4[0];
    if (nf_instance->num_of_ipv6) addr6 = nf_instance->ipv6[0];

    if (port) {
"""

PORT_SELECTION = """    if (nf_instance->num_of_ipv4) addr = nf_instance->ipv4[0];
    if (nf_instance->num_of_ipv6) addr6 = nf_instance->ipv6[0];

    if (!port && nf_instance->nf_type == OpenAPI_nf_type_UDR &&
        !nf_instance->fqdn && addr && nf_instance->num_of_ipv4 == 1 &&
        !nf_instance->num_of_ipv6) {
        port = udr_instance_advertised_port(nf_instance, scheme, addr);
        if (port) {
            inferred_addr = *addr;
            addr = &inferred_addr;
        }
    }

    if (port) {
"""


def replace_once(source, old, new, label):
    if source.count(old) != 1:
        raise SystemExit("STOP: expected exactly one " + label)
    return source.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = args.source_root.resolve()
    path = (root / "lib/sbi/context.c").resolve()
    try:
        path.relative_to(root)
    except ValueError:
        parser.error("source path escapes the Open5GS source root")

    if args.apply and (
        root != Path("/open5gs")
        or not Path("/run/open5gs-udr-port-build").is_file()
    ):
        parser.error("--apply requires the disposable /open5gs Docker build copy")

    original = path.read_text(encoding="utf-8")
    updated = replace_once(
        original,
        FUNCTION,
        HELPER + FUNCTION + "    ogs_sockaddr_t inferred_addr;\n",
        "NF instance client function",
    )
    updated = replace_once(
        updated, ADDRESS_SELECTION, PORT_SELECTION, "instance address selection"
    )

    if args.apply:
        path.write_text(updated, encoding="utf-8")
        print("PASS: applied UDR instance port patch to the Docker build copy")
    else:
        print("".join(difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile="a/lib/sbi/context.c",
            tofile="b/lib/sbi/context.c",
        )), end="")
        print("PASS: patch anchors matched; source was only read")


if __name__ == "__main__":
    main()
