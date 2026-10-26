// Experimental provider-side PDCP batch history tests.
#include "lib/e2/e2sm/e2sm_kpm/pdcp_batch_history.h"

namespace {

using history_type = ocudu::pdcp_batch_history;
using status_type = history_type::disposition;

history_type::time_point batch_time(int milliseconds)
{
  return history_type::time_point{} + std::chrono::milliseconds{milliseconds};
}

ocudu::pdcp_metrics_container make_batch(
    unsigned counter, uint32_t ue = 0, unsigned bearer = 1, bool drb = true)
{
  ocudu::pdcp_metrics_container metrics{};
  metrics.ue_index = ue;
  if (drb) {
    metrics.rb_id = ocudu::rb_id_t(
        static_cast<ocudu::drb_id_t>(bearer));
  } else {
    metrics.rb_id = ocudu::rb_id_t(
        static_cast<ocudu::srb_id_t>(bearer));
  }
  metrics.tx.counter = counter;
  metrics.rx.counter = counter;
  metrics.rx.num_sdus = 90;
  metrics.rx.num_data_pdus = 100;
  metrics.metrics_period = ocudu::timer_duration{1000};
  return metrics;
}

TEST(pdcp_batch_history_test, duplicate_does_not_refresh_age_or_revision)
{
  history_type history;
  const auto first = history.observe(make_batch(10), batch_time(0));
  ASSERT_TRUE(first.accepted);
  EXPECT_EQ(first.status, status_type::accepted);
  EXPECT_EQ(first.revision, 1U);

  const auto duplicate = history.observe(make_batch(10), batch_time(2000));
  EXPECT_FALSE(duplicate.accepted);
  EXPECT_EQ(duplicate.status, status_type::duplicate);
  const auto snapshot = history.collect(batch_time(2500));
  EXPECT_TRUE(snapshot.batches.empty());
  EXPECT_EQ(snapshot.expired, 1U);

  const auto next = history.observe(make_batch(11), batch_time(3000));
  EXPECT_TRUE(next.accepted);
  EXPECT_EQ(next.revision, 2U);
}

TEST(pdcp_batch_history_test, gap_records_missing_count_and_can_continue)
{
  history_type history;
  ASSERT_TRUE(history.observe(make_batch(10), batch_time(0)).accepted);
  const auto gap = history.observe(make_batch(13), batch_time(1000));
  EXPECT_TRUE(gap.accepted);
  EXPECT_EQ(gap.status, status_type::gap);
  EXPECT_EQ(gap.missing, 2U);
  const auto next = history.observe(make_batch(14), batch_time(2000));
  EXPECT_TRUE(next.accepted);
  EXPECT_EQ(next.status, status_type::accepted);
}

TEST(pdcp_batch_history_test, rollback_is_not_automatically_a_reset)
{
  history_type history;
  ASSERT_TRUE(history.observe(make_batch(20), batch_time(0)).accepted);
  const auto old = history.observe(make_batch(1), batch_time(1000));
  EXPECT_FALSE(old.accepted);
  EXPECT_EQ(old.status, status_type::counter_discontinuity);
  const auto snapshot = history.collect(batch_time(1000));
  ASSERT_EQ(snapshot.batches.size(), 1U);
  EXPECT_EQ(snapshot.batches.front().metrics.rx.counter, 20U);
  EXPECT_EQ(snapshot.batches.front().epoch, 1U);
  EXPECT_TRUE(history.observe(make_batch(21), batch_time(2000)).accepted);
}

TEST(pdcp_batch_history_test, mismatched_counters_do_not_advance_state)
{
  history_type history;
  ASSERT_TRUE(history.observe(make_batch(1), batch_time(0)).accepted);
  auto metrics = make_batch(2);
  metrics.tx.counter = 3;
  const auto rejected = history.observe(metrics, batch_time(1000));
  EXPECT_FALSE(rejected.accepted);
  EXPECT_EQ(rejected.status, status_type::mismatched);
  const auto next = history.observe(make_batch(2), batch_time(2000));
  EXPECT_TRUE(next.accepted);
  EXPECT_EQ(next.revision, 2U);
}

TEST(pdcp_batch_history_test, ordinary_unsigned_wrap_is_consecutive)
{
  history_type history;
  ASSERT_TRUE(history.observe(
      make_batch(std::numeric_limits<unsigned>::max()),
      batch_time(0)).accepted);
  const auto wrapped = history.observe(make_batch(0), batch_time(1000));
  EXPECT_TRUE(wrapped.accepted);
  EXPECT_EQ(wrapped.status, status_type::accepted);
  EXPECT_EQ(wrapped.missing, 0U);
}

TEST(pdcp_batch_history_test, ue_and_bearer_type_and_id_are_isolated)
{
  history_type history;
  EXPECT_TRUE(history.observe(make_batch(1, 0, 1), batch_time(0)).accepted);
  EXPECT_TRUE(history.observe(make_batch(1, 1, 1), batch_time(0)).accepted);
  EXPECT_TRUE(history.observe(make_batch(1, 0, 2), batch_time(0)).accepted);
  EXPECT_TRUE(history.observe(make_batch(1, 0, 1, false), batch_time(0)).accepted);
  EXPECT_EQ(history.collect(batch_time(1)).batches.size(), 4U);
  EXPECT_FALSE(history.observe(make_batch(1, 0, 1), batch_time(2)).accepted);
}

TEST(pdcp_batch_history_test, expiry_is_per_batch_and_boundary_is_exclusive)
{
  history_type history;
  ASSERT_TRUE(history.observe(make_batch(1), batch_time(0)).accepted);
  ASSERT_TRUE(history.observe(make_batch(2), batch_time(1000)).accepted);
  EXPECT_EQ(history.collect(batch_time(2499)).batches.size(), 2U);
  const auto snapshot = history.collect(batch_time(2500));
  ASSERT_EQ(snapshot.batches.size(), 1U);
  EXPECT_EQ(snapshot.expired, 1U);
  EXPECT_EQ(snapshot.batches.front().metrics.rx.counter, 2U);
}

TEST(pdcp_batch_history_test, capacity_is_bounded_per_source)
{
  history_type history(2);
  for (unsigned counter = 1; counter <= 3; ++counter) {
    ASSERT_TRUE(history.observe(
        make_batch(counter), batch_time(counter)).accepted);
  }
  EXPECT_TRUE(history.observe(make_batch(1, 1), batch_time(4)).accepted);
  const auto snapshot = history.collect(batch_time(5));
  ASSERT_EQ(snapshot.batches.size(), 3U);
  EXPECT_EQ(snapshot.batches[0].metrics.rx.counter, 2U);
  EXPECT_EQ(snapshot.batches[1].metrics.rx.counter, 3U);
  EXPECT_EQ(snapshot.batches[2].metrics.ue_index, 1U);
}

TEST(pdcp_batch_history_test, explicit_epoch_clears_only_selected_source)
{
  history_type history;
  const auto original = history.observe(make_batch(20), batch_time(0));
  ASSERT_TRUE(original.accepted);
  ASSERT_TRUE(history.observe(make_batch(7, 1), batch_time(0)).accepted);
  EXPECT_EQ(history.begin_epoch(history_type::key(make_batch(0))), 2U);
  ASSERT_EQ(history.collect(batch_time(1)).batches.size(), 1U);
  const auto restarted = history.observe(make_batch(0), batch_time(2));
  EXPECT_TRUE(restarted.accepted);
  EXPECT_EQ(restarted.epoch, 2U);
  EXPECT_GT(restarted.revision, original.revision);
  // This tests explicit epoch handling, not source-lifecycle detection.
}

TEST(pdcp_batch_history_test, regressed_receipt_time_is_rejected)
{
  history_type history;
  ASSERT_TRUE(history.observe(make_batch(1), batch_time(1000)).accepted);
  const auto rejected = history.observe(make_batch(2), batch_time(999));
  EXPECT_FALSE(rejected.accepted);
  EXPECT_EQ(rejected.status, status_type::time_regression);
  EXPECT_TRUE(history.observe(make_batch(2), batch_time(1001)).accepted);
}

} // namespace
