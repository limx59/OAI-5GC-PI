// Appended to e2_subscription_setup_test.cpp in the Docker source copy.
namespace {

class lifecycle_report_probe : public e2sm_report_service
{
public:
  unsigned collections = 0;
  unsigned header_window = 0;
  unsigned window = 17;

  bool collect_measurements() override
  {
    ++collections;
    return true;
  }

  bool is_ind_msg_ready() override { return true; }

  byte_buffer get_indication_header() override
  {
    header_window = window;
    return {};
  }

  byte_buffer get_indication_message() override
  {
    ++window;
    return {};
  }
};

class lifecycle_notifier : public e2_message_notifier
{
public:
  unsigned sent = 0;
  void on_new_message(const e2_message&) override { ++sent; }
};

class kpm_report_lifecycle : public ::testing::Test
{
protected:
  manual_task_worker worker{64};
  timer_manager timers;
  timer_factory factory{timers, worker};
  e2_event_manager events{factory};
  e2_subscription_info_t subscription{};
  lifecycle_notifier notifier;
  lifecycle_report_probe* probe = nullptr;
  ocudulog::basic_logger& logger = ocudulog::fetch_basic_logger("TEST");

  void SetUp() override
  {
    subscription.report_period = 1000;
    subscription.ran_function_id = 2;
    subscription.request_id.ric_requestor_id = 31;
    subscription.request_id.ric_instance_id = 47;
    auto service = std::make_unique<lifecycle_report_probe>();
    probe = service.get();
    subscription.action_list.push_back(
        {byte_buffer{}, 1, asn1::e2ap::ric_action_type_e::report, std::move(service)});
    events.add_sub_del_req(subscription.request_id, factory);
  }

  void tick(unsigned count)
  {
    for (unsigned i = 0; i != count; ++i) {
      timers.tick();
      worker.run_pending_tasks();
    }
  }

  void cancel()
  {
    asn1::e2ap::ric_sub_delete_request_s request;
    events.sub_del_reqs.at({31, 47})->set(request);
    worker.run_pending_tasks();
  }
};

TEST_F(kpm_report_lifecycle, deletion_does_not_collect_or_send)
{
  auto task = launch_async<e2ap_indication_procedure>(
      notifier, events, subscription, logger);
  EXPECT_FALSE(task.ready());
  cancel();
  EXPECT_TRUE(task.ready());
  EXPECT_EQ(probe->collections, 0U);
  EXPECT_EQ(notifier.sent, 0U);
  tick(2000);
  EXPECT_EQ(notifier.sent, 0U);
}

TEST_F(kpm_report_lifecycle, header_preserves_current_window_before_message_reset)
{
  auto task = launch_async<e2ap_indication_procedure>(
      notifier, events, subscription, logger);
  tick(1000);
  EXPECT_EQ(probe->collections, 1U);
  EXPECT_EQ(notifier.sent, 1U);
  EXPECT_EQ(probe->header_window, 17U);
  EXPECT_EQ(probe->window, 18U);
  cancel();
  EXPECT_TRUE(task.ready());
  EXPECT_EQ(probe->collections, 1U);
  EXPECT_EQ(notifier.sent, 1U);
}

} // namespace
