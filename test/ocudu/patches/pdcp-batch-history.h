// Experimental PDCP batch history for provider-side validation.
#pragma once

#include "ocudu/pdcp/pdcp_entity.h"
#include <chrono>
#include <cstdint>
#include <deque>
#include <limits>
#include <map>
#include <stdexcept>
#include <tuple>
#include <vector>

namespace ocudu {

class pdcp_batch_history
{
public:
  using clock = std::chrono::steady_clock;
  using time_point = clock::time_point;
  using key_type = std::tuple<uint32_t, bool, unsigned>;

  enum class disposition {
    accepted,
    gap,
    duplicate,
    counter_discontinuity,
    mismatched,
    time_regression
  };

  struct admission {
    disposition status;
    uint64_t revision;
    uint64_t epoch;
    uint64_t missing;
    bool accepted;
  };

  struct batch {
    pdcp_metrics_container metrics;
    time_point received;
    uint64_t revision;
    uint64_t epoch;
  };

  struct snapshot {
    std::vector<batch> batches;
    size_t expired = 0;
  };

  explicit pdcp_batch_history(
      size_t capacity_ = 10,
      std::chrono::milliseconds max_age_ = std::chrono::milliseconds{2500}) :
    capacity(capacity_), max_age(max_age_)
  {
    if (capacity == 0 || max_age.count() <= 0) {
      throw std::invalid_argument("Invalid PDCP history bounds");
    }
  }

  static key_type key(const pdcp_metrics_container& metrics)
  {
    const bool is_drb = metrics.rb_id.is_drb();
    const unsigned bearer = is_drb
        ? static_cast<unsigned>(metrics.rb_id.get_drb_id())
        : static_cast<unsigned>(metrics.rb_id.get_srb_id());
    return {metrics.ue_index, is_drb, bearer};
  }

  admission observe(const pdcp_metrics_container& metrics, time_point now)
  {
    auto& state = histories[key(metrics)];
    if (state.has_time && now < state.last_received) {
      return {disposition::time_regression, 0, state.epoch, 0, false};
    }
    if (metrics.tx.counter != metrics.rx.counter) {
      return {disposition::mismatched, 0, state.epoch, 0, false};
    }

    disposition status = disposition::accepted;
    uint64_t missing = 0;
    if (state.has_counter) {
      // Unsigned subtraction handles ordinary counter wrap. A half-range
      // or larger delta is ambiguous: old input, reset or discontinuity.
      const unsigned delta = metrics.rx.counter - state.last_counter;
      if (delta == 0) {
        return {disposition::duplicate, 0, state.epoch, 0, false};
      }
      constexpr unsigned half_range =
          std::numeric_limits<unsigned>::max() / 2U + 1U;
      if (delta >= half_range) {
        return {disposition::counter_discontinuity, 0, state.epoch, 0, false};
      }
      if (delta > 1) {
        status = disposition::gap;
        missing = static_cast<uint64_t>(delta) - 1;
      }
    }

    state.has_counter = true;
    state.last_counter = metrics.rx.counter;
    state.has_time = true;
    state.last_received = now;
    const uint64_t revision = ++next_revision;
    state.batches.push_back(batch{metrics, now, revision, state.epoch});
    while (state.batches.size() > capacity) {
      state.batches.pop_front();
    }
    return {status, revision, state.epoch, missing, true};
  }

  snapshot collect(time_point now) const
  {
    snapshot result;
    for (const auto& entry : histories) {
      for (const auto& item : entry.second.batches) {
        if (now < item.received) {
          throw std::invalid_argument("PDCP collection time regressed");
        }
        if (now - item.received >= max_age) {
          ++result.expired;
        } else {
          result.batches.push_back(item);
        }
      }
    }
    return result;
  }

  // Call only for an independently established source-lifecycle boundary.
  // A counter decrease alone is not evidence authorizing a new epoch.
  uint64_t begin_epoch(const key_type& source)
  {
    auto& state = histories[source];
    ++state.epoch;
    state.batches.clear();
    state.has_counter = false;
    state.has_time = false;
    return state.epoch;
  }

private:
  struct history {
    uint64_t epoch = 1;
    bool has_counter = false;
    unsigned last_counter = 0;
    bool has_time = false;
    time_point last_received{};
    std::deque<batch> batches;
  };

  size_t capacity;
  std::chrono::milliseconds max_age;
  uint64_t next_revision = 0;
  std::map<key_type, history> histories;
};

} // namespace ocudu
