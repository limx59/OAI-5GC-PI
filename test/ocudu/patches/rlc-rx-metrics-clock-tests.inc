// Appended to rlc_rx_tm_test.cpp in a disposable source copy.
namespace {

class rx_metrics_clock_notifier : public rlc_rx_tm_test_frame
{
public:
  std::vector<rlc_metrics> reports;
  void report_metrics(const rlc_metrics& report) override { reports.push_back(report); }
};

class rx_metrics_clock_environment
{
public:
  timer_manager protocol_clock;
  timer_manager metrics_clock;
  manual_task_worker worker{128};
  rx_metrics_clock_notifier notifier;
  null_rlc_pcap pcap;
  std::unique_ptr<rlc_bearer_metrics_collector> collector;
  std::unique_ptr<rlc_rx_tm_entity> rx;

  explicit rx_metrics_clock_environment(bool independent)
  {
    collector = std::make_unique<rlc_bearer_metrics_collector>(
        gnb_du_id_t{}, du_ue_index_t{}, rb_id_t{}, timer_duration{1000},
        &notifier, worker, independent ? &metrics_clock : nullptr);
    rx = std::make_unique<rlc_rx_tm_entity>(
        gnb_du_id_t::min, du_ue_index_t::MIN_DU_UE_INDEX, srb_id_t::srb0,
        make_default_srb0_rlc_config().tm.rx, notifier, *collector,
        pcap, worker, protocol_clock);
  }

  ~rx_metrics_clock_environment()
  {
    rx->stop();
    worker.run_pending_tasks();
    rx.reset();
  }

  void advance(timer_manager& clock, unsigned ticks)
  {
    for (unsigned i = 0; i != ticks; ++i) {
      clock.tick();
      worker.run_pending_tasks();
    }
  }

  void supply_tx_counter(uint32_t counter)
  {
    // Isolate the RX timer; TX components are supplied by the test.
    rlc_tx_metrics_higher high{};
    rlc_tx_metrics_lower low{};
    high.counter = counter;
    low.counter = counter;
    collector->push_tx_high_metrics(high);
    collector->push_tx_low_metrics(low);
    worker.run_pending_tasks();
  }
};

TEST_F(rlc_rx_tm_test, rx_metrics_clock_is_independent_of_protocol_clock)
{
  rx_metrics_clock_environment env(true);
  env.supply_tx_counter(0);
  env.advance(env.protocol_clock, 2000);
  EXPECT_TRUE(env.notifier.reports.empty());

  env.advance(env.metrics_clock, 999);
  EXPECT_TRUE(env.notifier.reports.empty());
  env.advance(env.metrics_clock, 1);
  ASSERT_EQ(env.notifier.reports.size(), 1U);
  EXPECT_EQ(env.notifier.reports[0].rx.counter, 0U);

  env.supply_tx_counter(1);
  env.advance(env.metrics_clock, 1000);
  ASSERT_EQ(env.notifier.reports.size(), 2U);
  EXPECT_EQ(env.notifier.reports[1].rx.counter, 1U);
}

TEST_F(rlc_rx_tm_test, rx_metrics_clock_defaults_to_protocol_clock)
{
  rx_metrics_clock_environment env(false);
  env.supply_tx_counter(0);
  env.advance(env.metrics_clock, 1000);
  EXPECT_TRUE(env.notifier.reports.empty());

  env.advance(env.protocol_clock, 999);
  EXPECT_TRUE(env.notifier.reports.empty());
  env.advance(env.protocol_clock, 1);
  ASSERT_EQ(env.notifier.reports.size(), 1U);
  EXPECT_EQ(env.notifier.reports[0].rx.counter, 0U);
}

} // namespace
