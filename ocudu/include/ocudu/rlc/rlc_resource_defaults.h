// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-FileCopyrightText: Copyright (C) 2026 OCUDU contributors
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#pragma once

namespace ocudu {

/// Default DRB receive window segment size.
constexpr unsigned rlc_drb_rx_window_seg_size = 256;
/// Default DRB receive window segment pool size.
constexpr unsigned rlc_drb_rx_window_seg_pool_size = 2048;
/// Default DRB transmit window segment size.
constexpr unsigned rlc_drb_tx_window_seg_size = 256;
/// Default DRB transmit window segment pool size.
constexpr unsigned rlc_drb_tx_window_seg_pool_size = 2048;

/// Default SRB receive window segment size.
constexpr unsigned rlc_srb_rx_window_seg_size = 8;
/// Default SRB receive window segment pool size.
constexpr unsigned rlc_srb_rx_window_seg_pool_size = 2048;
/// Default SRB transmit window segment size.
constexpr unsigned rlc_srb_tx_window_seg_size = 8;
/// Default SRB transmit window segment pool size.
constexpr unsigned rlc_srb_tx_window_seg_pool_size = 2048;

/// Default PDU recycler queue capacity: four times the maximum 18-bit AM window size (4 * 2^(18-1)).
constexpr unsigned rlc_pdu_recycler_size = 524288;

} // namespace ocudu
