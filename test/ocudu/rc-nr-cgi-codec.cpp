// Offline laboratory CGI codec check; no network or control requests.
#include "ocudu/asn1/e2sm/e2sm_common_ies.h"
#include <cstdio>
#include <cstdlib>

static void require(bool condition, const char* message)
{
  if (!condition) {
    std::fprintf(stderr, "%s\n", message);
    std::exit(EXIT_FAILURE);
  }
}

int main()
{
  for (uint64_t nci : {uint64_t{107520}, uint64_t{107521}}) {
    asn1::e2sm::nr_cgi_s source;
    source.ext = false;
    source.plmn_id.from_string("00f110");
    source.nr_cell_id.from_number(nci);

    ocudu::byte_buffer encoded;
    asn1::bit_ref writer(encoded);
    require(source.pack(writer) == asn1::OCUDUASN_SUCCESS, "CGI packing failed");
    require(encoded.length() == 9, "Unexpected encoded CGI length");

    asn1::e2sm::nr_cgi_s decoded;
    asn1::cbit_ref reader(encoded);
    require(decoded.unpack(reader) == asn1::OCUDUASN_SUCCESS, "CGI decoding failed");
    require(!decoded.ext, "Unexpected CGI extension");
    require(decoded.plmn_id.to_string() == "00f110", "PLMN round-trip mismatch");
    require(decoded.nr_cell_id.to_number() == nci, "NCI round-trip mismatch");

    std::printf("{\"nci\":%llu,\"plmn_hex\":\"00f110\",\"bytes\":9,\"hex\":\"",
                static_cast<unsigned long long>(nci));
    for (uint8_t value : encoded) {
      std::printf("%02x", static_cast<unsigned>(value));
    }
    std::printf("\",\"round_trip_passed\":true}\n");
  }
  return EXIT_SUCCESS;
}
