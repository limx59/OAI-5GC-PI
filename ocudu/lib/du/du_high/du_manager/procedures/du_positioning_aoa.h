// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-FileCopyrightText: Copyright (C) 2026 OCUDU contributors
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#pragma once

#include "ocudu/f1ap/du/f1ap_du_positioning_handler.h"
#include "ocudu/mac/mac_positioning_measurement_handler.h"
#include "ocudu/ran/positioning/common.h"
#include "ocudu/ran/positioning/ul_aoa_mapping.h"
#include "ocudu/support/ocudu_assert.h"
#include <optional>

namespace ocudu::odu {

/// \brief Returns the UL Angle of Arrival result of an SRS measurement, as per TS 38.473 section 9.3.1.167.
///
/// The MAC gives the angles in the LCS of the antenna array. The result carries the orientation of the array as the
/// LCS to GCS Translation, so that the LMF can convert the angles to the GCS. When the orientation is empty, the angles
/// are in the GCS.
///
/// \param[in] meas        SRS measurement of the MAC. It must contain the azimuth angle.
/// \param[in] orientation Orientation of the antenna array of the cell, if configured.
inline pos_meas_result_ul_aoa make_ul_aoa_result(const mac_positioning_measurement_response::ul_srs_pos_meas& meas,
                                                 const std::optional<lcs_to_gcs_translation_t>& orientation)
{
  ocudu_assert(meas.azimuth_aoa_deg.has_value(), "The SRS measurement has no azimuth angle of arrival");

  pos_meas_result_ul_aoa result{.azimuth_aoa = azimuth_aoa_to_reported_value(*meas.azimuth_aoa_deg)};
  if (meas.zenith_aoa_deg.has_value()) {
    result.zenith_aoa = zenith_aoa_to_reported_value(*meas.zenith_aoa_deg);
  }
  result.lcs_to_gcs_translation = orientation;
  return result;
}

/// \brief Returns the Zenith Angle of Arrival Information of a linear array measurement, as per TS 38.473 section
/// 9.3.1.239.
///
/// A linear array measures the broadside angle b. This is the angle to the plane normal to the array axis. The angle to
/// the array axis is therefore 90 - b. TS 38.473 section 9.3.1.239 reports this angle as the zenith in an LCS with the
/// z-axis along the array axis. A rotation of -90 degrees around the x-axis moves the y-axis of the array LCS onto
/// this z-axis. The slant of this LCS is therefore 90 degrees smaller, as per TS 38.901 section 7.1.3.
///
/// \param[in] broadside_deg Broadside angle, in degrees. Values: [-90, 90].
/// \param[in] orientation   Orientation of the antenna array of the cell.
inline pos_meas_result_zoa make_linear_array_zoa_result(float                           broadside_deg,
                                                        const lcs_to_gcs_translation_t& orientation)
{
  ocudu_assert(broadside_deg >= -90.0F && broadside_deg <= 90.0F,
               "Broadside angle {} degrees is outside [-90, 90].",
               broadside_deg);

  const float zenith_deg = 90.0F - broadside_deg;

  // The range {0,...,3599} of TS 38.473 section 9.3.1.241 encodes [0, 360) degrees in steps of 0.1 degrees.
  static constexpr uint16_t full_turn    = 3600;
  static constexpr uint16_t quarter_turn = 900;
  lcs_to_gcs_translation_t  axis_lcs     = orientation;
  axis_lcs.gamma                         = (orientation.gamma + full_turn - quarter_turn) % full_turn;

  return {.zenith_aoa = zenith_aoa_to_reported_value(zenith_deg), .lcs_to_gcs_translation = axis_lcs};
}

} // namespace ocudu::odu
