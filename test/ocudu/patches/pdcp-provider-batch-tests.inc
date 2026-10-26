// Append after pdcp-batch-history-tests.inc in the provider metrics test.
namespace {

class testable_pdcp_history_provider :
    public ocudu::e2sm_kpm_cu_up_meas_provider_impl
{
public:
  testable_pdcp_history_provider() { pdcp_batch_history_enabled = true; }

  void set_time(int milliseconds) { now = batch_time(milliseconds); }
  void disable_history() { pdcp_batch_history_enabled = false; }

  uint64_t new_epoch(const ocudu::pdcp_metrics_container& metrics)
  {
    return pdcp_history.begin_epoch(history_type::key(metrics));
  }

  bool read(std::vector<asn1::e2sm::meas_record_item_c>& items)
  {
    return get_packet_success_rate_ul_gnb_uu({}, {}, std::nullopt, items);
  }

protected:
  history_type::time_point pdcp_batch_now() const override { return now; }

private:
  history_type::time_point now = batch_time(0);
};

class pdcp_provider_batch_test : public ::testing::Test
{
protected:
  void SetUp() override { ocudulog::init(); }
  void TearDown() override { ocudulog::flush(); }

  void feed(unsigned counter, unsigned sdus, uint32_t ue = 0,
            unsigned bearer = 1)
  {
    auto metrics = make_batch(counter, ue, bearer);
    metrics.rx.num_sdus = sdus;
    provider.report_metrics(metrics);
  }

  void expect_value(unsigned value)
  {
    std::vector<asn1::e2sm::meas_record_item_c> items;
    ASSERT_TRUE(provider.read(items));
    ASSERT_EQ(items.size(), 1U);
    ASSERT_EQ(items.front().type(),
              asn1::e2sm::meas_record_item_c::types::integer);
    EXPECT_EQ(items.front().integer(), value);
  }

  void expect_no_value()
  {
    std::vector<asn1::e2sm::meas_record_item_c> items;
    ASSERT_TRUE(provider.read(items));
    ASSERT_EQ(items.size(), 1U);
    EXPECT_EQ(items.front().type(),
              asn1::e2sm::meas_record_item_c::types::no_value);
  }

  testable_pdcp_history_provider provider;
};

TEST_F(pdcp_provider_batch_test, duplicate_payload_does_not_bias_success_rate)
{
  feed(10, 90);
  provider.set_time(1000);
  feed(10, 0);
  expect_value(90);
  feed(11, 50);
  expect_value(70);
}

TEST_F(pdcp_provider_batch_test, repeated_duplicate_cannot_keep_cache_alive)
{
  feed(1, 90);
  provider.set_time(2000);
  feed(1, 0);
  expect_value(90);
  provider.set_time(2500);
  expect_no_value();
}

TEST_F(pdcp_provider_batch_test, gap_is_not_filled_with_fabricated_samples)
{
  feed(1, 90);
  provider.set_time(1000);
  feed(4, 50);
  expect_value(70);
}

TEST_F(pdcp_provider_batch_test, rollback_is_rejected_until_explicit_epoch)
{
  feed(20, 90);
  provider.set_time(1000);
  feed(0, 10);
  expect_value(90);
  EXPECT_EQ(provider.new_epoch(make_batch(0)), 2U);
  expect_no_value();
  feed(0, 10);
  expect_value(10);
  // This uses an explicit test lifecycle boundary, not automatic detection.
}

TEST_F(pdcp_provider_batch_test, mismatched_input_does_not_bias_success_rate)
{
  feed(1, 90);
  auto mismatched = make_batch(2);
  mismatched.tx.counter = 3;
  mismatched.rx.num_sdus = 0;
  provider.report_metrics(mismatched);
  expect_value(90);
}

TEST_F(pdcp_provider_batch_test, ue_and_bearer_counters_are_independent)
{
  feed(1, 90, 0, 1);
  feed(1, 60, 0, 2);
  feed(1, 30, 1, 1);
  expect_value(60);
}

TEST_F(pdcp_provider_batch_test, expired_samples_are_excluded_individually)
{
  feed(1, 90);
  provider.set_time(1000);
  feed(2, 50);
  provider.set_time(2500);
  expect_value(50);
  provider.set_time(3500);
  expect_no_value();
}

TEST_F(pdcp_provider_batch_test, absent_or_zero_denominator_is_unavailable)
{
  expect_no_value();
  auto empty = make_batch(1);
  empty.rx.num_sdus = 0;
  empty.rx.num_data_pdus = 0;
  provider.report_metrics(empty);
  expect_no_value();
}

TEST_F(pdcp_provider_batch_test, disabled_history_retains_legacy_cache_behavior)
{
  provider.disable_history();
  feed(1, 90);
  provider.set_time(3000);
  feed(1, 50);
  expect_value(70);
}

} // namespace
