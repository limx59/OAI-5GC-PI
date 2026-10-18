// Appended to rlc_tx_tm_test.cpp in a disposable source copy.
namespace {

class metrics_clock_notifier : public rlc_tx_tm_test_frame
{
public:
  std::vector<rlc_metrics> reports;
  void report_metrics(const rlc_metrics& report) override { reports.push_back(report); }
};

class tx_metrics_clock_environment
{
public:
  timer_manager protocol_clock;
  timer_manager metrics_clock;
  manual_task_worker cell_worker{128};
  manual_task_worker ue_worker{128};
  metrics_clock_notifier notifier;
  null_rlc_pcap pcap;
  byte_buffer_recycler recycler{
      ue_worker, rlc_pdu_recycler_size, ocudulog::fetch_basic_logger("RLC", false)};
  std::unique_ptr<rlc_bearer_metrics_collector> collector;
  std::unique_ptr<rlc_tx_tm_entity> tx;

  explicit tx_metrics_clock_environment(bool independent)
  {
    collector = std::make_unique<rlc_bearer_metrics_collector>(
        gnb_du_id_t{}, du_ue_index_t{}, rb_id_t{}, timer_duration{1000},
        &notifier, ue_worker, independent ? &metrics_clock : nullptr);
    auto config = make_default_srb0_rlc_config().tm.tx;
    tx = std::make_unique<rlc_tx_tm_entity>(
        gnb_du_id_t::min, du_ue_index_t::MIN_DU_UE_INDEX, srb_id_t::srb0,
        config, notifier, notifier, notifier, *collector, pcap,
        cell_worker, ue_worker, protocol_clock, recycler);
  }

  ~tx_metrics_clock_environment()
  {
    tx->stop();
    cell_worker.run_pending_tasks();
    ue_worker.run_pending_tasks();
    tx.reset();
  }

  void advance(timer_manager& clock, unsigned ticks)
  {
    for (unsigned i = 0; i != ticks; ++i) {
      clock.tick();
      cell_worker.run_pending_tasks();
      ue_worker.run_pending_tasks();
    }
  }

  void supply_rx_counter(uint32_t counter)
  {
    // Isolate TX high/low timer behavior; RX is supplied by the test.
    rlc_rx_metrics rx{};
    rx.counter = counter;
    collector->push_rx_high_metrics(rx);
    ue_worker.run_pending_tasks();
  }
};

TEST_F(rlc_tx_tm_test, metrics_clock_is_independent_of_protocol_clock)
{
  tx_metrics_clock_environment env(true);
  unsigned protocol_expirations = 0;
  auto protocol_timer =
      timer_factory{env.protocol_clock, env.ue_worker}.create_timer();
  protocol_timer.set(std::chrono::milliseconds{500},
                     [&]() { ++protocol_expirations; });
  protocol_timer.run();

  env.supply_rx_counter(0);
  env.advance(env.protocol_clock, 2000);
  EXPECT_EQ(protocol_expirations, 1U);
  EXPECT_TRUE(env.notifier.reports.empty());

  env.advance(env.metrics_clock, 999);
  EXPECT_TRUE(env.notifier.reports.empty());
  env.advance(env.metrics_clock, 1);
  ASSERT_EQ(env.notifier.reports.size(), 1U);
  EXPECT_EQ(env.notifier.reports[0].tx.tx_high.counter, 0U);
  EXPECT_EQ(env.notifier.reports[0].tx.tx_low.counter, 0U);
  EXPECT_EQ(protocol_expirations, 1U);

  env.supply_rx_counter(1);
  env.advance(env.metrics_clock, 1000);
  ASSERT_EQ(env.notifier.reports.size(), 2U);
  EXPECT_EQ(env.notifier.reports[1].tx.tx_high.counter, 1U);
  EXPECT_EQ(env.notifier.reports[1].tx.tx_low.counter, 1U);
}

TEST_F(rlc_tx_tm_test, metrics_clock_defaults_to_protocol_clock)
{
  tx_metrics_clock_environment env(false);
  env.supply_rx_counter(0);
  env.advance(env.metrics_clock, 1000);
  EXPECT_TRUE(env.notifier.reports.empty());

  env.advance(env.protocol_clock, 999);
  EXPECT_TRUE(env.notifier.reports.empty());
  env.advance(env.protocol_clock, 1);
  ASSERT_EQ(env.notifier.reports.size(), 1U);
  EXPECT_EQ(env.notifier.reports[0].tx.tx_high.counter, 0U);
  EXPECT_EQ(env.notifier.reports[0].tx.tx_low.counter, 0U);
}

} // namespace
