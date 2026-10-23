// Experimental PDCP statistics-clock isolation tests.
namespace ocudu {

class pdcp_rx_metrics_clock_test :
    public pdcp_rx_test_helper_manual_crypto, public ::testing::Test
{
protected:
  timer_manager statistics_timers;

  void SetUp() override
  {
    ocudulog::init();
    set_sn_size(pdcp_sn_size::size12bits);
    set_algo(1);
    set_header_compression(cfg_rohc_disabled.config);
    init();
    pdcp_rx->stop();
    pdcp_rx.reset();
    worker.run_pending_tasks();
    metrics_notif.metrics_list.clear();
    pdcp_rx = std::make_unique<pdcp_entity_rx>(
        0, drb_id_t::drb1, config, *test_frame, *test_frame,
        timer_factory{timers, worker}, worker, crypto_exec,
        nof_crypto_threads, *pdcp_rohc_factory, *metrics_agg,
        timer_factory{statistics_timers, worker});
    pdcp_rx->set_status_handler(test_frame.get());
    pdcp_rx->set_feedback_handler(test_frame.get());
  }

  void TearDown() override
  {
    pdcp_rx->stop();
    pdcp_rx.reset();
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

TEST_F(pdcp_rx_metrics_clock_test, statistics_do_not_advance_reordering_timer)
{
  pdcp_rx->configure_security(
      sec_cfg, security::integrity_enabled::on, security::ciphering_enabled::on);
  pdcp_rx->set_state(pdcp_rx_state{.rx_next = 0, .rx_deliv = 0, .rx_reord = 0});
  byte_buffer pdu;
  get_test_pdu(1, pdu);
  pdcp_rx->handle_pdu(byte_buffer_chain::create(std::move(pdu)).value());
  wait_pending_crypto();
  worker.run_pending_tasks();
  ASSERT_TRUE(test_frame->sdu_queue.empty());

  tick_statistics(300);
  ASSERT_EQ(metrics_notif.metrics_list.size(), 3U);
  const auto first_counter = metrics_notif.metrics_list.front().rx.counter;
  for (unsigned i = 0; i != 3; ++i) {
    const auto& m = metrics_notif.metrics_list[i].rx;
    EXPECT_EQ(m.counter, first_counter + i);
    EXPECT_EQ(m.num_data_pdus, i == 0 ? 1U : 0U);
    EXPECT_EQ(m.num_t_reordering_timeouts, 0U);
  }
  EXPECT_TRUE(test_frame->sdu_queue.empty());

  tick_all(150);
  EXPECT_EQ(metrics_notif.metrics_list.size(), 3U);
  ASSERT_EQ(test_frame->sdu_queue.size(), 1U);
  tick_statistics(100);
  ASSERT_EQ(metrics_notif.metrics_list.size(), 4U);
  EXPECT_EQ(metrics_notif.metrics_list.back().rx.num_t_reordering_timeouts, 1U);
}

TEST_F(pdcp_rx_metrics_clock_test, protocol_clock_does_not_emit_statistics)
{
  tick_all(300);
  EXPECT_TRUE(metrics_notif.metrics_list.empty());
  tick_statistics(100);
  ASSERT_EQ(metrics_notif.metrics_list.size(), 1U);
}

} // namespace ocudu
