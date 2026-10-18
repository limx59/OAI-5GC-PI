// Regression tests for an isolated copy of the RLC collector test source.
#include <limits>

TEST_F(rlc_berarer_metrics_collector_test, preserves_matched_counter_including_wraparound)
{
  const uint32_t counters[] = {
      0U, 1U, std::numeric_limits<uint32_t>::max(), 0U};
  size_t expected_reports = 0;

  for (uint32_t counter : counters) {
    rlc_tx_metrics_higher high{};
    rlc_tx_metrics_lower low{};
    rlc_rx_metrics rx{};
    high.counter = counter;
    low.counter = counter;
    rx.counter = counter;

    metrics_coll->push_tx_high_metrics(high);
    ue_worker.run_pending_tasks();
    ASSERT_EQ(metrics_notif->metrics_list.size(), expected_reports);

    metrics_coll->push_tx_low_metrics(low);
    ue_worker.run_pending_tasks();
    ASSERT_EQ(metrics_notif->metrics_list.size(), expected_reports);

    metrics_coll->push_rx_high_metrics(rx);
    ue_worker.run_pending_tasks();
    ++expected_reports;
    ASSERT_EQ(metrics_notif->metrics_list.size(), expected_reports);

    const auto& report = metrics_notif->metrics_list.back();
    EXPECT_EQ(report.counter, counter);
    EXPECT_EQ(report.tx.tx_high.counter, counter);
    EXPECT_EQ(report.tx.tx_low.counter, counter);
    EXPECT_EQ(report.rx.counter, counter);
    EXPECT_EQ(report.metrics_period, timer_duration{1000});
  }
}
