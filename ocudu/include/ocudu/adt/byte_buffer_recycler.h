// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-FileCopyrightText: Copyright (C) 2026 OCUDU contributors
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI

#pragma once

#include "ocudu/adt/byte_buffer.h"
#include "ocudu/adt/spsc_queue.h"
#include "ocudu/ocudulog/ocudulog.h"
#include "ocudu/support/executors/task_executor.h"

namespace ocudu {

/// \brief Deferred destruction bin for byte_buffer objects, intended to offload memory reclamation off a
/// time-critical execution path.
///
/// The caller accumulates byte_buffers via recycle() and periodically calls flush() to dispatch their
/// destruction to a background executor. If the internal queue is full, recycle() destroys the buffer
/// immediately on the calling thread as a fallback.
///
/// \note Single-producer/single-consumer: recycle() and flush() must be called from a single serialized
/// context (e.g. one UE strand). The background executor is the sole consumer.
class byte_buffer_recycler
{
public:
  byte_buffer_recycler(task_executor& executor_, size_t capacity, ocudulog::basic_logger& logger_) :
    exec(executor_), logger(logger_), bin(capacity)
  {
  }

  ~byte_buffer_recycler()
  {
    // Executor may be stopped at teardown — drain synchronously to avoid leaks.
    drain();
  }

  /// \brief Hands a byte_buffer over for deferred destruction.
  ///
  /// The buffer will be destroyed on the background executor after the next flush(). If the queue is
  /// full, the buffer is destroyed immediately on the calling thread as a fallback.
  /// The caller is responsible for calling flush() after recycling one or more buffers.
  void recycle(byte_buffer buf)
  {
    if (not bin.try_push(std::move(buf))) {
      logger.warning("byte_buffer_recycler: queue full, destroying buffer on calling thread");
    }
  }

  /// \brief Dispatches destruction of all buffered byte_buffers to the background executor.
  ///
  /// Shall be called by the owner after one or more recycle() calls. Logs an error if the executor
  /// rejects the task.
  void flush()
  {
    if (not exec.execute([this]() { drain(); })) {
      logger.warning("byte_buffer_recycler: failed to dispatch flush to executor");
    }
  }

private:
  void drain()
  {
    byte_buffer buf;
    while (bin.try_pop(buf)) {
    }
  }

  task_executor&          exec;
  ocudulog::basic_logger& logger;
  concurrent_queue<byte_buffer, concurrent_queue_policy::lockfree_spsc, concurrent_queue_wait_policy::non_blocking> bin;
};

} // namespace ocudu
