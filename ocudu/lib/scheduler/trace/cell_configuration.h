// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-FileCopyrightText: Copyright (C) 2026 OCUDU contributors
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#pragma once

#include "ocudu/ran/bwp/bwp_configuration.h"
#include "ocudu/ran/pci.h"
#include "ocudu/ran/pdcch/coreset.h"
#include "ocudu/ran/pdcch/search_space.h"
#include "ocudu/ran/pucch/pucch_configuration.h"
#include "ocudu/ran/pucch/pucch_constants.h"
#include "ocudu/ran/resource_allocation/vrb_to_prb.h"

namespace ocudu::schedtrace {

/// Maximum number of contiguous CRB ranges of a CORESET.
constexpr size_t MAX_NOF_CORESET_CRB_RANGES = (pdcch_constants::MAX_NOF_FREQ_RESOURCES + 1) / 2;

/// CORESET of the cell.
struct cell_coreset {
  coreset_id id;
  /// Contiguous CRB ranges of the CORESET, in increasing order.
  static_vector<crb_interval, MAX_NOF_CORESET_CRB_RANGES> crbs;
  /// Duration in symbols.
  uint8_t duration;
  /// Interleaved CCE-to-REG mapping. Absent for the non-interleaved mapping.
  std::optional<coreset_configuration::interleaved_mapping_type> interleaving;
};

/// Search space of the cell.
struct cell_search_space {
  search_space_id id;
  coreset_id      cs_id;
  bool            is_common;
  /// Monitoring symbols within slot. SearchSpace#0 has one entry per SSB index, other search spaces a single one.
  static_vector<search_space_configuration::monitoring_symbols_within_slot_t, MAX_NOF_SS0_SSB_CANDIDATES>
      monitoring_symbols;
};

/// PRACH configuration of the cell.
struct cell_prach_config {
  /// prach-ConfigurationIndex.
  uint8_t config_index;
  /// msg1-FrequencyStart, in PRBs of the initial UL BWP.
  uint16_t frequency_start;
  /// msg1-SubcarrierSpacing. Invalid if derived from the prach-ConfigurationIndex.
  subcarrier_spacing scs;
};

/// Initial DL BWP of the cell.
struct dl_bwp_configuration {
  bwp_configuration                                       generic_params;
  static_vector<cell_coreset, MAX_NOF_CORESETS>           coresets;
  static_vector<cell_search_space, MAX_NOF_SEARCH_SPACES> search_spaces;
  /// vrb-ToPRB-Interleaver of UE PDSCHs scheduled with DCI format 1_1.
  vrb_to_prb::mapping_type pdsch_vrb_to_prb = vrb_to_prb::mapping_type::non_interleaved;
};

/// Initial UL BWP of the cell.
struct ul_bwp_configuration {
  bwp_configuration                                                          generic_params;
  static_vector<pucch_resource, pucch_constants::MAX_NOF_TOT_CELL_RESOURCES> pucch_resources;
  std::optional<cell_prach_config>                                           prach;
};

struct cell_configuration {
  pci_t                pci;
  dl_bwp_configuration init_dl_bwp;
  ul_bwp_configuration init_ul_bwp;
};

} // namespace ocudu::schedtrace
