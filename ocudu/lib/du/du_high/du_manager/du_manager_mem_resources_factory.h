// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-FileCopyrightText: Copyright (C) 2026 OCUDU contributors
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#pragma once

#include "ocudu/du/du_high/du_manager/du_manager_mem_resources.h"

namespace ocudu {
class task_executor;
} // namespace ocudu

namespace ocudu::odu {

struct du_manager_params;

/// \brief Creates a shared PDU recycler for deferred byte_buffer destruction off the RLC RT path.
std::unique_ptr<byte_buffer_recycler> make_byte_buffer_recycler(size_t capacity, task_executor& exec);

du_manager_mem_resources create_du_manager_mem_resources(const du_manager_params& du_params);

} // namespace ocudu::odu
