// Appended to e2_subscription_setup_test.cpp in the Docker source copy.
TEST_F(e2_test_subscriber, kpm_report_uses_independent_timer)
{
  timer_manager report_clock;
  timer_factory report_factory{report_clock, task_worker};

  // Recreate the E2 implementation with an independent report timer.
  e2 = std::make_unique<e2_impl>(e2_impl_dependencies{
      .logger = test_logger,
      .agent_notifier = *agent_notifier,
      .timers = factory,
      .e2_client = *e2_client,
      .subscription_mngr = *e2_subscription_mngr,
      .e2sm_mngr = *e2sm_mngr,
      .task_exec = task_worker,
      .kpm_report_timers = report_factory});
  ASSERT_TRUE(e2->handle_e2_tnl_connection_request());

  const auto function_id = e2sm_kpm_asn1_packer::ran_func_id;
  e2sm_mngr->add_supported_ran_function(function_id, e2sm_kpm_asn1_packer::oid);
  e2_subscription_mngr->add_ran_function_oid(function_id, e2sm_kpm_asn1_packer::oid);

  const uint8_t encoded[] = {
      0x00, 0x08, 0x40, 0x2b, 0x00, 0x00, 0x03, 0x00, 0x1d, 0x00, 0x05, 0x00,
      0x00, 0x7b, 0x00, 0x15, 0x00, 0x05, 0x00, 0x02, 0x00, 0x01, 0x00, 0x1e,
      0x00, 0x15, 0x00, 0x04, 0x01, 0x02, 0x03, 0x04, 0x00, 0x00, 0x13, 0x40,
      0x0a, 0x60, 0x01, 0x00, 0x04, 0x01, 0x02, 0x03, 0x04, 0x02, 0x00};
  auto bytes = byte_buffer::create(encoded, encoded + sizeof(encoded)).value();
  asn1::cbit_ref reader(bytes);
  e2_message request;
  ASSERT_EQ(request.pdu.unpack(reader), asn1::OCUDUASN_SUCCESS);
  auto& subscription_request = request.pdu.init_msg().value.ric_sub_request();
  subscription_request->ran_function_id = function_id;
  const auto request_id = subscription_request->ric_request_id;

  e2->handle_message(request);
  task_worker.run_pending_tasks();
  ASSERT_EQ(e2_client->last_tx_e2_pdu.pdu.type().value,
            asn1::e2ap::e2ap_pdu_c::types_opts::successful_outcome);

  for (unsigned i = 0; i != 2000; ++i) {
    tick();
  }
  EXPECT_EQ(e2_client->last_tx_e2_pdu.pdu.type().value,
            asn1::e2ap::e2ap_pdu_c::types_opts::successful_outcome);

  for (unsigned i = 0; i != 1500; ++i) {
    report_clock.tick();
    task_worker.run_pending_tasks();
  }
  EXPECT_EQ(e2_client->last_tx_e2_pdu.pdu.type().value,
            asn1::e2ap::e2ap_pdu_c::types_opts::init_msg);
  if (e2_client->last_tx_e2_pdu.pdu.type().value ==
      asn1::e2ap::e2ap_pdu_c::types_opts::init_msg) {
    EXPECT_EQ(e2_client->last_tx_e2_pdu.pdu.init_msg().value.type(),
              asn1::e2ap::e2ap_elem_procs_o::init_msg_c::types_opts::ric_ind);
  }

  e2_message deletion;
  deletion.pdu.set_init_msg().load_info_obj(ASN1_E2AP_ID_RIC_SUB_DELETE);
  auto& delete_request = deletion.pdu.init_msg().value.ric_sub_delete_request();
  delete_request->ric_request_id = request_id;
  delete_request->ran_function_id = function_id;
  e2->handle_message(deletion);
  task_worker.run_pending_tasks();
  EXPECT_EQ(e2_client->last_tx_e2_pdu.pdu.type().value,
            asn1::e2ap::e2ap_pdu_c::types_opts::successful_outcome);

  // Destroy timer users before the independent timer manager.
  e2_subscription_mngr->stop();
  e2.reset();
}
