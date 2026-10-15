// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-FileCopyrightText: Copyright (C) 2026 OCUDU contributors
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#pragma once

#include <linux/capability.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace ocudu {
namespace app_services {

/// Raises the permitted Linux capabilities of the calling thread into its effective set.
inline void raise_permitted_capabilities()
{
  // File capabilities without the effective bit only fill the permitted set, so an execve succeeds whatever subset of
  // them the caller allows. On failure the effective set stays as it is.
  __user_cap_header_struct header                         = {_LINUX_CAPABILITY_VERSION_3, 0};
  __user_cap_data_struct   data[_LINUX_CAPABILITY_U32S_3] = {};
  if (::syscall(SYS_capget, &header, data) != 0) {
    return;
  }
  for (__user_cap_data_struct& word : data) {
    word.effective = word.permitted;
  }
  ::syscall(SYS_capset, &header, data);
}

} // namespace app_services
} // namespace ocudu
