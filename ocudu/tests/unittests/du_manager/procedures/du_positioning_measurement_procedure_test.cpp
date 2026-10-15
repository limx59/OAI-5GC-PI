// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-FileCopyrightText: Copyright (C) 2026 OCUDU contributors
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#include "du_manager_procedure_test_helpers.h"
#include "lib/du/du_high/du_manager/du_ue/du_ue_manager.h"
#include "lib/du/du_high/du_manager/procedures/du_positioning_aoa.h"
#include "lib/du/du_high/du_manager/procedures/du_positioning_measurement_procedure.h"
#include "ocudu/du/du_cell_config_helpers.h"
#include "ocudu/support/async/async_test_utils.h"
#include <gtest/gtest.h>

using namespace ocudu;
using namespace odu;

namespace {

/// Orientation of the antenna array of the test cell, in the TS 38.473 Section 9.3.1.241 encoding.
constexpr lcs_to_gcs_translation_t test_orientation{.alpha = 2700, .beta = 60, .gamma = 0};

std::vector<du_cell_config> make_test_cells()
{
  std::vector<du_cell_config> cells = {config_helpers::make_default_du_cell_config()};
  cells[0].trp_antenna_orientation  = test_orientation;
  return cells;
}

/// Builds an SRS configuration with one periodic resource.
srs_config make_test_srs_config()
{
  srs_config cfg{};
  cfg.srs_res_list.resize(1);
  cfg.srs_res_list[0].id.ue_res_id   = srs_config::MIN_SRS_RES_ID;
  cfg.srs_res_list[0].id.cell_res_id = 0;
  cfg.srs_res_list[0].sequence_id    = 1;
  cfg.srs_res_list[0].periodicity_and_offset =
      srs_config::srs_periodicity_and_offset{.period = srs_periodicity::sl80, .offset = 0};
  cfg.srs_res_set_list.resize(1);
  cfg.srs_res_set_list[0].res_type.emplace<srs_config::srs_resource_set::periodic_resource_type>();
  return cfg;
}

class du_positioning_measurement_procedure_test : public du_manager_proc_tester, public ::testing::Test
{
protected:
  explicit du_positioning_measurement_procedure_test(std::vector<du_cell_config> cells = make_test_cells()) :
    du_manager_proc_tester(std::move(cells))
  {
    ocudulog::fetch_basic_logger("DU-MNG").set_level(ocudulog::basic_levels::debug);
    ocudulog::init();

    // The TRP IDs start from 1, as in du_positioning_manager_impl.
    du_trp_info trp;
    trp.trp_id = trp_id_t::min;
    trp.cgi    = cell_mng.get_cell_cfg(to_du_cell_index(0)).nr_cgi;
    trps.emplace(trp.trp_id, trp);
  }

  ~du_positioning_measurement_procedure_test() override { ocudulog::flush(); }

  du_positioning_meas_request make_request()
  {
    du_positioning_meas_request req;
    req.trp_meas_req_list.push_back(du_trp_meas_request{.trp_id = trp_id_t::min});
    req.pos_meas_quants.push_back(positioning_meas_quantity{.meas_type = pos_meas_type::ul_rtoa});
    srs_carrier carrier;
    carrier.srs_cfg        = make_test_srs_config();
    carrier.ul_bwp_cfg.scs = subcarrier_spacing::kHz15;
    req.srs_carriers.push_back(carrier);
    return req;
  }

  /// Programs the MAC to report an angle of arrival on the next measurement request.
  void mac_reports_aoa(std::optional<float> azimuth_deg, std::optional<float> zenith_deg)
  {
    auto& mac_resp = mac.next_positioning_meas_response;
    mac_resp.cell_results.resize(1);
    mac_resp.cell_results[0].ul_srs_pos_meass.resize(1);
    mac_resp.cell_results[0].ul_srs_pos_meass[0].azimuth_aoa_deg = azimuth_deg;
    mac_resp.cell_results[0].ul_srs_pos_meass[0].zenith_aoa_deg  = zenith_deg;
  }

  /// Builds a request for the UL Angle of Arrival.
  du_positioning_meas_request make_aoa_request()
  {
    du_positioning_meas_request req = make_request();
    req.pos_meas_quants             = {positioning_meas_quantity{.meas_type = pos_meas_type::ul_aoa}};
    return req;
  }

  du_positioning_meas_response run_procedure(const du_positioning_meas_request& req)
  {
    async_task<du_positioning_meas_response> t =
        launch_async<positioning_measurement_procedure>(req, cell_mng, real_ue_mng, params, trps);
    lazy_task_launcher<du_positioning_meas_response> launcher{t};
    ocudu_assert(launcher.ready(), "The positioning measurement procedure should have completed by now");
    return t.get();
  }

  du_ue_manager                   real_ue_mng{params, mem_resources, cell_res_alloc, cell_mng, proc_metrics};
  std::map<trp_id_t, du_trp_info> trps;
};

/// Test cell without an orientation of the antenna array.
class du_positioning_measurement_procedure_without_orientation_test : public du_positioning_measurement_procedure_test
{
protected:
  du_positioning_measurement_procedure_without_orientation_test() :
    du_positioning_measurement_procedure_test({config_helpers::make_default_du_cell_config()})
  {
  }
};

/// Test cell with an orientation of the antenna array and the Zenith Angle of Arrival reports enabled.
class du_positioning_measurement_procedure_with_zenith_aoa_test : public du_positioning_measurement_procedure_test
{
protected:
  du_positioning_measurement_procedure_with_zenith_aoa_test() :
    du_positioning_measurement_procedure_test(make_zenith_aoa_test_cells())
  {
  }

  static std::vector<du_cell_config> make_zenith_aoa_test_cells()
  {
    std::vector<du_cell_config> cells = make_test_cells();
    cells[0].trp_report_zenith_aoa    = true;
    return cells;
  }
};

} // namespace

/// The MAC answers with an empty response when the measurement times out, or when it already runs another
/// measurement. The procedure must report a failure instead of reading a result that the MAC did not produce.
TEST_F(du_positioning_measurement_procedure_test, when_mac_reports_no_measurement_then_the_response_is_empty)
{
  // The MAC test double returns an empty response by default.
  du_positioning_meas_response resp = run_procedure(make_request());

  ASSERT_TRUE(resp.pos_meas_list.empty());
}

TEST_F(du_positioning_measurement_procedure_test, when_request_is_sent_then_the_mac_timeout_follows_the_srs_period)
{
  run_procedure(make_request());

  ASSERT_TRUE(mac.last_positioning_meas_request.has_value());
  // Two periods of 80 slots at 15 kHz.
  ASSERT_EQ(mac.last_positioning_meas_request->timeout, std::chrono::milliseconds{160});
}

/// The gNB-CU expects the result within the Response Time, as per TS 38.473 section 8.13.2.2, so a shorter Response
/// Time caps the time that the MAC waits.
TEST_F(du_positioning_measurement_procedure_test, when_response_time_is_shorter_then_it_caps_the_mac_timeout)
{
  du_positioning_meas_request req = make_request();
  req.response_time               = std::chrono::milliseconds{50};

  run_procedure(req);

  ASSERT_TRUE(mac.last_positioning_meas_request.has_value());
  // The measurement stops before the Response Time, so that the answer still arrives inside it.
  ASSERT_EQ(mac.last_positioning_meas_request->timeout, std::chrono::milliseconds{40});
}

/// A very short Response Time still starts a measurement, which then ends in a failure.
TEST_F(du_positioning_measurement_procedure_test,
       when_response_time_is_shorter_than_the_margin_then_the_wait_stays_positive)
{
  du_positioning_meas_request req = make_request();
  req.response_time               = std::chrono::milliseconds{10};

  run_procedure(req);

  ASSERT_TRUE(mac.last_positioning_meas_request.has_value());
  ASSERT_GT(mac.last_positioning_meas_request->timeout.count(), 0);
  ASSERT_LT(mac.last_positioning_meas_request->timeout, std::chrono::milliseconds{10});
}

/// A Response Time longer than the SRS period does not extend the wait.
TEST_F(du_positioning_measurement_procedure_test, when_response_time_is_longer_then_the_srs_period_decides)
{
  du_positioning_meas_request req = make_request();
  req.response_time               = std::chrono::milliseconds{5000};

  run_procedure(req);

  ASSERT_TRUE(mac.last_positioning_meas_request.has_value());
  // Two periods of 80 slots at 15 kHz.
  ASSERT_EQ(mac.last_positioning_meas_request->timeout, std::chrono::milliseconds{160});
}

TEST_F(du_positioning_measurement_procedure_test, when_the_cell_has_an_antenna_orientation_then_the_aoa_carries_it)
{
  mac_reports_aoa(123.4F, 56.7F);

  du_positioning_meas_response resp = run_procedure(make_aoa_request());

  ASSERT_EQ(resp.pos_meas_list.size(), 1);
  ASSERT_EQ(resp.pos_meas_list[0].results.size(), 1);
  const auto* aoa = std::get_if<pos_meas_result_ul_aoa>(&resp.pos_meas_list[0].results[0]);
  ASSERT_NE(aoa, nullptr);
  // The angles are encoded as per TS 38.133, Table 13.4.1-1 and Table 13.4.1-2.
  ASSERT_EQ(aoa->azimuth_aoa, 3034);
  ASSERT_EQ(aoa->zenith_aoa, 567);
  ASSERT_TRUE(aoa->lcs_to_gcs_translation.has_value());
  ASSERT_EQ(aoa->lcs_to_gcs_translation->alpha, test_orientation.alpha);
  ASSERT_EQ(aoa->lcs_to_gcs_translation->beta, test_orientation.beta);
  ASSERT_EQ(aoa->lcs_to_gcs_translation->gamma, test_orientation.gamma);
}

/// A linear array measures the broadside angle. The DU reports it as the azimuth in the LCS of the array.
TEST_F(du_positioning_measurement_procedure_test,
       when_zenith_aoa_reports_are_disabled_then_the_broadside_angle_is_reported_as_the_azimuth)
{
  mac_reports_aoa(30.0F, std::nullopt);

  du_positioning_meas_response resp = run_procedure(make_aoa_request());

  ASSERT_EQ(resp.pos_meas_list.size(), 1);
  ASSERT_EQ(resp.pos_meas_list[0].results.size(), 1);
  const auto* aoa = std::get_if<pos_meas_result_ul_aoa>(&resp.pos_meas_list[0].results[0]);
  ASSERT_NE(aoa, nullptr);
  ASSERT_EQ(aoa->azimuth_aoa, 2100);
  ASSERT_FALSE(aoa->zenith_aoa.has_value());
  ASSERT_TRUE(aoa->lcs_to_gcs_translation.has_value());
  ASSERT_EQ(aoa->lcs_to_gcs_translation->alpha, test_orientation.alpha);
  ASSERT_EQ(aoa->lcs_to_gcs_translation->beta, test_orientation.beta);
  ASSERT_EQ(aoa->lcs_to_gcs_translation->gamma, test_orientation.gamma);
}

/// A linear array measures the broadside angle. With the Zenith Angle of Arrival reports enabled, the DU reports the
/// angle to the array axis.
TEST_F(du_positioning_measurement_procedure_with_zenith_aoa_test,
       when_the_mac_reports_no_zenith_then_the_angle_to_the_array_axis_is_reported)
{
  mac_reports_aoa(30.0F, std::nullopt);

  du_positioning_meas_response resp = run_procedure(make_aoa_request());

  ASSERT_EQ(resp.pos_meas_list.size(), 1);
  ASSERT_EQ(resp.pos_meas_list[0].results.size(), 1);
  const auto* zoa = std::get_if<pos_meas_result_zoa>(&resp.pos_meas_list[0].results[0]);
  ASSERT_NE(zoa, nullptr);
  // The angle to the array axis is 90 - 30 = 60 degrees, in 0.1 degree steps.
  ASSERT_EQ(zoa->zenith_aoa, 600);
  // The z-axis of the LCS is the array axis, so the slant is 90 degrees smaller than the one of the array.
  ASSERT_TRUE(zoa->lcs_to_gcs_translation.has_value());
  ASSERT_EQ(zoa->lcs_to_gcs_translation->alpha, test_orientation.alpha);
  ASSERT_EQ(zoa->lcs_to_gcs_translation->beta, test_orientation.beta);
  ASSERT_EQ(zoa->lcs_to_gcs_translation->gamma, 2700);
}

TEST_F(du_positioning_measurement_procedure_without_orientation_test,
       when_the_cell_has_no_antenna_orientation_then_the_aoa_has_no_lcs_to_gcs_translation)
{
  mac_reports_aoa(30.0F, std::nullopt);

  du_positioning_meas_response resp = run_procedure(make_aoa_request());

  ASSERT_EQ(resp.pos_meas_list.size(), 1);
  ASSERT_EQ(resp.pos_meas_list[0].results.size(), 1);
  const auto* aoa = std::get_if<pos_meas_result_ul_aoa>(&resp.pos_meas_list[0].results[0]);
  ASSERT_NE(aoa, nullptr);
  ASSERT_EQ(aoa->azimuth_aoa, 2100);
  ASSERT_FALSE(aoa->zenith_aoa.has_value());
  ASSERT_FALSE(aoa->lcs_to_gcs_translation.has_value());
}

TEST(du_positioning_aoa_test, linear_array_zenith_covers_the_whole_broadside_range)
{
  const lcs_to_gcs_translation_t orientation{.alpha = 0, .beta = 0, .gamma = 0};

  ASSERT_EQ(make_linear_array_zoa_result(90.0F, orientation).zenith_aoa, 0);
  ASSERT_EQ(make_linear_array_zoa_result(0.0F, orientation).zenith_aoa, 900);
  // The zenith of 180 degrees falls in the last reported value interval.
  ASSERT_EQ(make_linear_array_zoa_result(-90.0F, orientation).zenith_aoa, 1799);
}

TEST(du_positioning_aoa_test, linear_array_slant_wraps_around_a_full_turn)
{
  const lcs_to_gcs_translation_t orientation{.alpha = 100, .beta = 200, .gamma = 900};

  const pos_meas_result_zoa zoa = make_linear_array_zoa_result(0.0F, orientation);

  ASSERT_TRUE(zoa.lcs_to_gcs_translation.has_value());
  ASSERT_EQ(zoa.lcs_to_gcs_translation->alpha, 100);
  ASSERT_EQ(zoa.lcs_to_gcs_translation->beta, 200);
  ASSERT_EQ(zoa.lcs_to_gcs_translation->gamma, 0);
}
