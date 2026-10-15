// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-FileCopyrightText: Copyright (C) 2026 OCUDU contributors
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#include "du_manager_mem_resources_factory.h"
#include "ocudu/adt/format.h"
#include "ocudu/du/du_high/du_manager/du_manager_params.h"
#include "ocudu/ocudulog/ocudulog.h"

using namespace ocudu;
using namespace odu;

std::unique_ptr<byte_buffer_recycler> odu::make_byte_buffer_recycler(size_t capacity, task_executor& exec)
{
  return std::make_unique<byte_buffer_recycler>(exec, capacity, ocudulog::fetch_basic_logger("RLC"));
}

du_manager_mem_resources odu::create_du_manager_mem_resources(const du_manager_params& du_params)
{
  std::vector<std::unique_ptr<rlc_drb_tx_window_seg_pool, rlc_pool_deleter>> drb_tx_window_seg_pools;
  std::vector<std::unique_ptr<rlc_srb_tx_window_seg_pool, rlc_pool_deleter>> srb_tx_window_seg_pools;
  std::vector<std::unique_ptr<byte_buffer_recycler>>                         pdu_recyclers;
  for (unsigned c = 0; c < du_params.ran.cells.size(); c++) {
    drb_tx_window_seg_pools.push_back(make_rlc_drb_tx_window_seg_pool(du_params.rlc.drb_tx_window_seg_pool_size,
                                                                      du_params.rlc.drb_tx_window_seg_size));
    srb_tx_window_seg_pools.push_back(make_rlc_srb_tx_window_seg_pool(du_params.rlc.srb_tx_window_seg_pool_size,
                                                                      du_params.rlc.srb_tx_window_seg_size));
    pdu_recyclers.push_back(make_byte_buffer_recycler(du_params.rlc.pdu_recycler_size,
                                                      du_params.services.ue_execs.rlc_shared_low_prio_exec()));
  }
  return du_manager_mem_resources{
      {make_rlc_drb_rx_window_seg_pool(du_params.rlc.drb_rx_window_seg_pool_size, du_params.rlc.drb_rx_window_seg_size),
       std::move(drb_tx_window_seg_pools),
       make_rlc_srb_rx_window_seg_pool(du_params.rlc.srb_rx_window_seg_pool_size, du_params.rlc.srb_rx_window_seg_size),
       std::move(srb_tx_window_seg_pools),
       std::move(pdu_recyclers)}};
}
