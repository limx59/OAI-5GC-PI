// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-FileCopyrightText: Copyright (C) 2026 OCUDU contributors
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#include "apps/units/flexible_o_du/o_du_high/du_high/du_high_config_cli11_schema.h"
#include "apps/units/flexible_o_du/o_du_high/du_high/du_high_config_translators.h"
#include "tests/ocudu_test_requirements.h"
#include "ocudu/support/config_parsers.h"
#include <cstdio>
#include <fstream>
#include <gtest/gtest.h>
#include <unistd.h>

using namespace ocudu;

namespace {

/// Config file that lives only for the duration of a test.
class temp_config_file
{
public:
  explicit temp_config_file(const std::string& contents) : file_path("/tmp/du_high_antenna_orientation_test_XXXXXX")
  {
    const int fd = ::mkstemp(file_path.data());
    report_fatal_error_if_not(fd != -1, "Failed to create the temporary config file");
    ::close(fd);
    std::ofstream{file_path} << contents;
  }
  ~temp_config_file() { ::remove(file_path.c_str()); }

  const std::string& path() const { return file_path; }

private:
  std::string file_path;
};

/// Parses a DU high configuration out of a YAML text and generates the DU cell configurations, as the application
/// does.
std::vector<odu::du_cell_config> parse_cells(const std::string& yaml_text)
{
  const temp_config_file cfg_file(yaml_text);

  CLI::App app{"du_high_antenna_orientation_config_test"};
  app.config_formatter(create_yaml_config_parser());
  app.allow_config_extras(CLI::config_extras_mode::error);
  std::string cfg_path;
  app.set_config("-c,", cfg_path, "Read config from file", false);

  du_high_parsed_config parsed_cfg;
  configure_cli11_with_du_high_config_schema(app, parsed_cfg);

  const std::vector<const char*> argv = {"du_high_antenna_orientation_config_test", "-c", cfg_file.path().c_str()};
  app.parse(static_cast<int>(argv.size()), argv.data());
  autoderive_du_high_parameters_after_parsing(parsed_cfg.config);

  return generate_du_cell_config(parsed_cfg.config);
}

} // namespace

TEST(du_high_antenna_orientation_config_test, orientation_is_converted_to_the_lcs_to_gcs_translation)
{
  OCUDU_TEST_REQUIREMENTS("MVP-FUNC-POS-16-3-c");

  const std::vector<odu::du_cell_config> cells = parse_cells(R"(
cell_cfg:
  antenna_orientation:
    bearing: 270.04
    downtilt: 355
    slant: 359.97
)");

  ASSERT_EQ(cells.size(), 1);
  ASSERT_TRUE(cells[0].trp_antenna_orientation.has_value());
  // The range {0,...,3599} of TS 38.473, Section 9.3.1.241 encodes [0, 360) degrees in steps of 0.1 degrees.
  EXPECT_EQ(cells[0].trp_antenna_orientation->alpha, 2700);
  EXPECT_EQ(cells[0].trp_antenna_orientation->beta, 3550);
  EXPECT_EQ(cells[0].trp_antenna_orientation->gamma, 0);
}

TEST(du_high_antenna_orientation_config_test, cell_without_orientation_has_no_lcs_to_gcs_translation)
{
  OCUDU_TEST_REQUIREMENTS("MVP-FUNC-POS-16-3-c");

  const std::vector<odu::du_cell_config> cells = parse_cells(R"(
cells:
  - pci: 1
    antenna_orientation:
      bearing: 90
  - pci: 2
)");

  ASSERT_EQ(cells.size(), 2);
  ASSERT_TRUE(cells[0].trp_antenna_orientation.has_value());
  EXPECT_EQ(cells[0].trp_antenna_orientation->alpha, 900);
  EXPECT_FALSE(cells[1].trp_antenna_orientation.has_value());
}

TEST(du_high_antenna_orientation_config_test, angle_outside_0_to_360_degrees_is_rejected)
{
  OCUDU_TEST_REQUIREMENTS("MVP-FUNC-POS-16-3-c");

  // The angles of the LCS to GCS Translation have the range [0, 360) degrees, as per TS 38.473, Section 9.3.1.241.
  EXPECT_THROW(parse_cells("cell_cfg:\n  antenna_orientation:\n    bearing: 360\n"), CLI::ParseError);
  EXPECT_THROW(parse_cells("cell_cfg:\n  antenna_orientation:\n    downtilt: -5\n"), CLI::ParseError);
}

TEST(du_high_antenna_orientation_config_test, zenith_aoa_reports_are_disabled_unless_configured)
{
  OCUDU_TEST_REQUIREMENTS("MVP-FUNC-POS-16-3-c");

  const std::vector<odu::du_cell_config> cells = parse_cells(R"(
cells:
  - pci: 1
    antenna_orientation:
      bearing: 90
  - pci: 2
    antenna_orientation:
      bearing: 90
      report_zenith_aoa: true
)");

  ASSERT_EQ(cells.size(), 2);
  EXPECT_FALSE(cells[0].trp_report_zenith_aoa);
  EXPECT_TRUE(cells[1].trp_report_zenith_aoa);
}
