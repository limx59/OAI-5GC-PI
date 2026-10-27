// Source-instance tests; appended after existing history/provider tests.
#include "lib/pdcp/pdcp_metrics_aggregator.h"
#include <memory>

namespace {

// Synchronous executor for deterministic unit tests only.
class pdcp_source_test_executor : public ocudu::task_executor
{
public:
  bool execute(ocudu::unique_task task) override
  {
    task();
    return true;
  }
  bool defer(ocudu::unique_task task) override
  {
    task();
    return true;
  }
};

class pdcp_source_instance_test : public pdcp_provider_batch_test
{
protected:
  class forwarding_notifier : public ocudu::pdcp_metrics_notifier
  {
  public:
    explicit forwarding_notifier(testable_pdcp_history_provider& provider_) :
      provider(provider_) {}

    void report_metrics(const ocudu::pdcp_metrics_container& metrics) override
    {
      reports.push_back(metrics);
      provider.report_metrics(metrics);
    }

    testable_pdcp_history_provider& provider;
    std::vector<ocudu::pdcp_metrics_container> reports;
  };

  std::unique_ptr<ocudu::pdcp_metrics_aggregator>
  create_source(uint32_t ue = 0, unsigned bearer = 1)
  {
    return std::make_unique<ocudu::pdcp_metrics_aggregator>(
        ue, ocudu::rb_id_t(static_cast<ocudu::drb_id_t>(bearer)),
        ocudu::timer_duration{1000}, &notifier, executor);
  }

  void emit(ocudu::pdcp_metrics_aggregator& source,
            unsigned counter, unsigned sdus)
  {
    auto metrics = make_batch(counter);
    metrics.rx.num_sdus = sdus;
    source.push_tx_metrics(metrics.tx);
    source.push_rx_metrics(metrics.rx);
  }

  pdcp_source_test_executor executor;
  forwarding_notifier notifier{provider};
};

TEST_F(pdcp_source_instance_test, reconstruction_recovers_and_rejects_late_old_report)
{
  auto source = create_source();
  emit(*source, 20, 90);
  ASSERT_EQ(notifier.reports.size(), 1U);
  const auto old = notifier.reports.back();
  ASSERT_GT(old.source_instance, 0U);
  expect_value(90);

  source.reset();
  provider.set_time(1000);
  source = create_source();
  emit(*source, 0, 10);
  ASSERT_EQ(notifier.reports.size(), 2U);
  EXPECT_GT(notifier.reports.back().source_instance, old.source_instance);
  expect_value(10);

  provider.set_time(2000);
  provider.report_metrics(old);
  expect_value(10);
  provider.set_time(3500);
  expect_no_value();
}

TEST_F(pdcp_source_instance_test, same_instance_rollback_is_not_a_restart)
{
  auto source = create_source();
  emit(*source, 20, 90);
  ASSERT_FALSE(notifier.reports.empty());
  const auto identity = notifier.reports.back().source_instance;
  provider.set_time(1000);
  emit(*source, 0, 10);
  EXPECT_EQ(notifier.reports.back().source_instance, identity);
  expect_value(90);
  emit(*source, 21, 50);
  expect_value(70);
}

TEST_F(pdcp_source_instance_test, duplicate_and_gap_use_real_aggregator_reports)
{
  auto source = create_source();
  emit(*source, 1, 90);
  provider.set_time(1000);
  emit(*source, 1, 0);
  expect_value(90);
  emit(*source, 4, 50);
  expect_value(70);
}

TEST_F(pdcp_source_instance_test, replacement_waits_for_matching_tx_rx)
{
  auto old = create_source();
  emit(*old, 20, 90);
  old.reset();
  provider.set_time(1000);
  auto replacement = create_source();
  auto metrics = make_batch(0);
  metrics.rx.num_sdus = 10;
  const auto count = notifier.reports.size();
  replacement->push_tx_metrics(metrics.tx);
  EXPECT_EQ(notifier.reports.size(), count);
  expect_value(90);
  replacement->push_rx_metrics(metrics.rx);
  EXPECT_EQ(notifier.reports.size(), count + 1);
  expect_value(10);
}

TEST_F(pdcp_source_instance_test, replacement_preserves_other_bearer_history)
{
  auto first = create_source(0, 1);
  auto second = create_source(0, 2);
  emit(*first, 20, 90);
  const auto delayed = notifier.reports.back();
  emit(*second, 7, 50);
  expect_value(70);

  first.reset();
  provider.set_time(1000);
  first = create_source(0, 1);
  emit(*first, 0, 10);
  expect_value(30);
  provider.report_metrics(delayed);
  expect_value(30);
}

TEST_F(pdcp_source_instance_test, replacement_with_higher_counter_starts_new_history)
{
  auto source = create_source();
  emit(*source, 20, 90);
  source.reset();
  provider.set_time(1000);
  source = create_source();
  emit(*source, 21, 10);
  expect_value(10);
}

TEST_F(pdcp_source_instance_test, history_records_epoch_and_rejects_old_or_unspecified_source)
{
  history_type history;
  auto metrics = make_batch(20);
  metrics.source_instance = 100;
  const auto first = history.observe(metrics, batch_time(0));
  ASSERT_TRUE(first.accepted);
  EXPECT_EQ(first.epoch, 1U);

  metrics = make_batch(0);
  metrics.source_instance = 101;
  const auto restarted = history.observe(metrics, batch_time(1000));
  ASSERT_TRUE(restarted.accepted);
  EXPECT_EQ(restarted.status, status_type::source_restart);
  EXPECT_EQ(restarted.epoch, 2U);
  EXPECT_EQ(restarted.missing, 0U);
  EXPECT_GT(restarted.revision, first.revision);

  for (uint64_t identity : {uint64_t{100}, uint64_t{0}}) {
    metrics.source_instance = identity;
    const auto stale = history.observe(metrics, batch_time(2000));
    EXPECT_FALSE(stale.accepted);
    EXPECT_EQ(stale.status, status_type::stale_source);
    EXPECT_EQ(stale.epoch, 2U);
  }
  const auto snapshot = history.collect(batch_time(2000));
  ASSERT_EQ(snapshot.batches.size(), 1U);
  EXPECT_EQ(snapshot.batches.front().metrics.source_instance, 101U);
  EXPECT_TRUE(history.collect(batch_time(3500)).batches.empty());
}

TEST_F(pdcp_source_instance_test, invalid_new_source_does_not_clear_valid_history)
{
  history_type history;
  auto metrics = make_batch(20);
  metrics.source_instance = 100;
  ASSERT_TRUE(history.observe(metrics, batch_time(1000)).accepted);

  metrics = make_batch(0);
  metrics.source_instance = 101;
  metrics.tx.counter = 1;
  const auto mismatch = history.observe(metrics, batch_time(2000));
  EXPECT_FALSE(mismatch.accepted);
  EXPECT_EQ(mismatch.status, status_type::mismatched);

  metrics.tx.counter = 0;
  const auto regressed = history.observe(metrics, batch_time(999));
  EXPECT_FALSE(regressed.accepted);
  EXPECT_EQ(regressed.status, status_type::time_regression);

  const auto before = history.collect(batch_time(2000));
  ASSERT_EQ(before.batches.size(), 1U);
  EXPECT_EQ(before.batches.front().epoch, 1U);
  EXPECT_EQ(before.batches.front().metrics.source_instance, 100U);

  const auto valid = history.observe(metrics, batch_time(2000));
  EXPECT_TRUE(valid.accepted);
  EXPECT_EQ(valid.status, status_type::source_restart);
  EXPECT_EQ(valid.epoch, 2U);
}

} // namespace
