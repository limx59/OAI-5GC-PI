// Appended to the metrics test source only in a disposable build container.
#include <limits>

TEST_F(e2sm_kpm_meas_provider_metrics_test, rlc_revision_tracks_source_counter_without_consuming)
{
  auto sample = generate_non_zero_rlc_metrics(0, 1);
  auto set_counter = [&](uint32_t counter) {
    sample.tx.tx_low.counter = counter;
    sample.tx.tx_high.counter = counter;
    sample.rx.counter = counter;
  };
  auto revision = [&]() {
    return du_meas_provider->get_rlc_source_revision(0, drb_id_t{1});
  };

  EXPECT_FALSE(revision().has_value());
  set_counter(0);
  metrics->report_metrics(sample);
  auto first = revision();
  ASSERT_TRUE(first.has_value());

  // Independent readers observe the same revision without consuming it.
  EXPECT_EQ(revision(), first);
  EXPECT_EQ(revision(), first);

  // Re-delivery of the same source counter is not a new measurement.
  metrics->report_metrics(sample);
  EXPECT_EQ(revision(), first);

  // Equal measurement values with a new source counter are still fresh.
  set_counter(1);
  metrics->report_metrics(sample);
  auto next = revision();
  ASSERT_TRUE(next.has_value());
  EXPECT_GT(*next, *first);

  set_counter(std::numeric_limits<uint32_t>::max());
  metrics->report_metrics(sample);
  auto before_wrap = revision();
  ASSERT_TRUE(before_wrap.has_value());
  EXPECT_GT(*before_wrap, *next);

  set_counter(0);
  metrics->report_metrics(sample);
  auto after_wrap = revision();
  ASSERT_TRUE(after_wrap.has_value());
  EXPECT_GT(*after_wrap, *before_wrap);
}

TEST_F(e2sm_kpm_meas_provider_metrics_test, rlc_revisions_are_separate_for_ues_and_bearers)
{
  auto first_sample = generate_non_zero_rlc_metrics(0, 1);
  first_sample.tx.tx_low.counter = 7;
  first_sample.tx.tx_high.counter = 7;
  first_sample.rx.counter = 7;
  metrics->report_metrics(first_sample);

  auto first = du_meas_provider->get_rlc_source_revision(0, drb_id_t{1});
  ASSERT_TRUE(first.has_value());

  auto other_bearer = first_sample;
  other_bearer.rb_id = rb_id_t(drb_id_t{2});
  metrics->report_metrics(other_bearer);
  auto second = du_meas_provider->get_rlc_source_revision(0, drb_id_t{2});
  ASSERT_TRUE(second.has_value());
  EXPECT_GT(*second, *first);
  EXPECT_EQ(du_meas_provider->get_rlc_source_revision(0, drb_id_t{1}), first);

  auto other_ue = first_sample;
  other_ue.ue_index = to_du_ue_index(1);
  metrics->report_metrics(other_ue);
  auto third = du_meas_provider->get_rlc_source_revision(1, drb_id_t{1});
  ASSERT_TRUE(third.has_value());
  EXPECT_GT(*third, *second);
  EXPECT_EQ(du_meas_provider->get_rlc_source_revision(0, drb_id_t{1}), first);
}

TEST_F(e2sm_kpm_meas_provider_metrics_test, mismatched_rlc_component_counters_do_not_advance_revision)
{
  auto sample = generate_non_zero_rlc_metrics(0, 1);
  sample.tx.tx_low.counter = 3;
  sample.tx.tx_high.counter = 3;
  sample.rx.counter = 3;
  metrics->report_metrics(sample);
  auto first = du_meas_provider->get_rlc_source_revision(0, drb_id_t{1});
  ASSERT_TRUE(first.has_value());

  sample.tx.tx_low.counter = 4;
  metrics->report_metrics(sample);
  EXPECT_EQ(du_meas_provider->get_rlc_source_revision(0, drb_id_t{1}), first);

  sample.tx.tx_high.counter = 4;
  sample.rx.counter = 4;
  metrics->report_metrics(sample);
  auto next = du_meas_provider->get_rlc_source_revision(0, drb_id_t{1});
  ASSERT_TRUE(next.has_value());
  EXPECT_GT(*next, *first);
}
