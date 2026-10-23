// Experimental PDCP statistics-clock isolation tests.
namespace ocudu {

class pdcp_tx_metrics_clock_test :
    public pdcp_tx_test_helper_manual_crypto, public ::testing::Test
{
protected:
  timer_manager statistics_timers;

  void SetUp() override
  {
    ocudulog::init();
    init(std::make_tuple(pdcp_sn_size::size12bits, 1U, cfg_rohc_disabled),
         pdcp_rb_type::drb, pdcp_rlc_mode::am, pdcp_discard_timer::ms150);
    pdcp_tx->stop();
    pdcp_tx.reset();
    worker.run_pending_tasks();
    metrics_notif.metrics_list.clear();
    pdcp_tx = std::make_unique<pdcp_entity_tx>(
        0, drb_id_t::drb1, config, test_frame, test_frame,
        timer_factory{timers, worker}, worker, crypto_exec,
        nof_crypto_threads, *pdcp_rohc_factory, *metrics_agg,
        timer_factory{statistics_timers, worker});
    pdcp_tx->set_status_provider(&test_frame);
    pdcp_tx->handle_desired_buffer_size_notification(20 * (1 << 20));
  }

  void TearDown() override
  {
    pdcp_tx->stop();
    pdcp_tx.reset();
    worker.run_pending_tasks();
    ocudulog::flush();
  }

  void tick_statistics(unsigned count)
  {
    for (unsigned i = 0; i != count; ++i) {
      statistics_timers.tick();
      worker.run_pending_tasks();
    }
  }
};

TEST_F(pdcp_tx_metrics_clock_test, statistics_do_not_advance_discard_timer)
{
  pdcp_tx->configure_security(
      sec_cfg, security::integrity_enabled::on, security::ciphering_enabled::on);
  pdcp_tx->handle_sdu(byte_buffer::create(sdu1).value());
  wait_pending_crypto();
  worker.run_pending_tasks();
  ASSERT_EQ(test_frame.pdu_queue.size(), 1U);
  pdcp_tx->handle_transmit_notification(pdcp_compute_sn(1, sn_size));

  tick_statistics(300);
  ASSERT_EQ(metrics_notif.metrics_list.size(), 3U);
  const auto first_counter = metrics_notif.metrics_list.front().tx.counter;
  for (unsigned i = 0; i != 3; ++i) {
    const auto& m = metrics_notif.metrics_list[i].tx;
    EXPECT_EQ(m.counter, first_counter + i);
    EXPECT_EQ(m.num_sdus, i == 0 ? 1U : 0U);
    EXPECT_EQ(m.num_discard_timeouts, 0U);
  }
  EXPECT_TRUE(test_frame.sdu_discard_queue.empty());

  tick_all(200);
  EXPECT_EQ(metrics_notif.metrics_list.size(), 3U);
  ASSERT_EQ(test_frame.sdu_discard_queue.size(), 1U);
  tick_statistics(100);
  ASSERT_EQ(metrics_notif.metrics_list.size(), 4U);
  EXPECT_EQ(metrics_notif.metrics_list.back().tx.num_discard_timeouts, 1U);
}

TEST_F(pdcp_tx_metrics_clock_test, protocol_clock_does_not_emit_statistics)
{
  tick_all(300);
  EXPECT_TRUE(metrics_notif.metrics_list.empty());
  tick_statistics(100);
  ASSERT_EQ(metrics_notif.metrics_list.size(), 1U);
}

} // namespace ocudu
