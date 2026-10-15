// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-FileCopyrightText: Copyright (C) 2026 OCUDU contributors
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#include "lib/scheduler/trace/trace_file_format.h"
#include <fmt/format.h>
#include <fstream>
#include <gtest/gtest.h>
#include <iterator>
#include <vector>

using namespace ocudu;
using namespace schedtrace;

namespace {

/// Hash of the binary schema of a released file format version.
struct schema_version_hash {
  uint16_t major;
  uint16_t minor;
  uint64_t hash;
};

} // namespace

/// Binary schema hash of every file format version, oldest first.
static constexpr schema_version_hash schema_hashes[] = {
    {1, 0, 0xf95e2d23bcc5bb59},
};

/// Computes the 64-bit FNV-1a hash of the given bytes.
static uint64_t fnv1a_64(const std::vector<uint8_t>& bytes)
{
  uint64_t hash = 0xcbf29ce484222325ULL;
  for (uint8_t byte : bytes) {
    hash ^= byte;
    hash *= 0x100000001b3ULL;
  }
  return hash;
}

TEST(trace_file_format_test, header_roundtrip)
{
  const trace_file_version                          version{0x1234, 0xabcd};
  const std::array<uint8_t, trace_file_header_size> header  = make_trace_file_header(version);
  const std::optional<trace_file_version>           decoded = parse_trace_file_header(header);
  ASSERT_TRUE(decoded.has_value());
  EXPECT_EQ(decoded->major, version.major);
  EXPECT_EQ(decoded->minor, version.minor);
  // Little-endian, after the magic bytes.
  EXPECT_EQ(header[4], 0x34);
  EXPECT_EQ(header[5], 0x12);
}

TEST(trace_file_format_test, header_with_wrong_magic_is_rejected)
{
  std::array<uint8_t, trace_file_header_size> header = make_trace_file_header();
  header[0]                                          = 0;
  EXPECT_FALSE(parse_trace_file_header(header).has_value());
}

TEST(trace_file_format_test, schema_changes_bump_the_file_format_version)
{
  std::ifstream file(SCHEDTRACE_BINARY_SCHEMA, std::ios::binary);
  ASSERT_TRUE(file.is_open()) << "Missing binary schema " << SCHEDTRACE_BINARY_SCHEMA;
  const std::vector<uint8_t> bfbs{std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
  const uint64_t             hash = fnv1a_64(bfbs);

  const schema_version_hash& latest = std::end(schema_hashes)[-1];
  EXPECT_EQ(latest.major, trace_file_version_major);
  EXPECT_EQ(latest.minor, trace_file_version_minor);
  EXPECT_EQ(latest.hash, hash) << fmt::format(
      "The schedtrace schema changed. Bump the file format version in fbs/cell_event.fbs and append "
      "{{{}, {}, {:#x}}} with the new version to schema_hashes. If only the flatc version changed, "
      "update the hash of the latest entry instead.",
      trace_file_version_major,
      trace_file_version_minor,
      hash);

  for (unsigned i = 1; i < std::size(schema_hashes); ++i) {
    const schema_version_hash& prev = schema_hashes[i - 1];
    const schema_version_hash& curr = schema_hashes[i];
    EXPECT_TRUE(curr.major > prev.major or (curr.major == prev.major and curr.minor > prev.minor))
        << "Versions in schema_hashes must be strictly increasing";
  }
}
