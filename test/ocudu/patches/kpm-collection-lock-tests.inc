// Appended after kpm-style4-record-guard-tests.inc in the Docker source copy.
#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.h"
#include <chrono>
#include <future>
#include <thread>

namespace {

class style4_lock_probe_provider : public style4_guard_meas_provider
{
public:
  std::recursive_mutex mutex;
  unsigned acquisitions = 0;

  std::unique_lock<std::recursive_mutex> lock_measurements() override
  {
    ++acquisitions;
    return std::unique_lock<std::recursive_mutex>{mutex};
  }

  bool get_meas_data(const meas_type_c& type,
                     const label_info_list_l labels,
                     const std::vector<ue_id_c>& ues,
                     const std::optional<cgi_c> cell,
                     std::vector<meas_record_item_c>& items) override
  {
    bool acquired = std::async(std::launch::async, [this]() {
      std::unique_lock<std::recursive_mutex> probe(mutex, std::try_to_lock);
      return probe.owns_lock();
    }).get();
    EXPECT_FALSE(acquired);
    return style4_guard_meas_provider::get_meas_data(type, labels, ues, cell, items);
  }
};

TEST(e2sm_kpm_collection_lock, collection_holds_one_view_and_releases_before_encoding)
{
  style4_lock_probe_provider provider;
  provider.fault_enabled = false;
  e2sm_kpm_report_service_style4 service(make_style4_guard_action(), provider);
  ASSERT_TRUE(service.collect_measurements());
  EXPECT_EQ(provider.acquisitions, 1U);
  EXPECT_TRUE(std::async(std::launch::async, [&provider]() {
    std::unique_lock<std::recursive_mutex> probe(provider.mutex, std::try_to_lock);
    return probe.owns_lock();
  }).get());
  ASSERT_TRUE(service.is_ind_msg_ready());
  auto bytes = service.get_indication_message();
  e2sm_kpm_ind_msg_s message;
  asn1::cbit_ref reader(bytes);
  ASSERT_EQ(message.unpack(reader), asn1::OCUDUASN_SUCCESS);
  EXPECT_EQ(message.ind_msg_formats.ind_msg_format3().ue_meas_report_list.size(), 2U);
}

TEST(e2sm_kpm_collection_lock, failed_collection_releases_view)
{
  style4_lock_probe_provider provider;
  e2sm_kpm_report_service_style4 service(make_style4_guard_action(), provider);
  EXPECT_FALSE(service.collect_measurements());
  EXPECT_FALSE(service.is_ind_msg_ready());
  EXPECT_TRUE(std::async(std::launch::async, [&provider]() {
    std::unique_lock<std::recursive_mutex> probe(provider.mutex, std::try_to_lock);
    return probe.owns_lock();
  }).get());
}

TEST(e2sm_kpm_collection_lock, du_cache_paths_respect_collection_lock)
{
  dummy_f1ap_ue_id_translator translator;
  e2sm_kpm_du_meas_provider_impl provider(translator);
  for (unsigned operation = 0; operation != 4; ++operation) {
    SCOPED_TRACE(operation);
    auto guard = provider.lock_measurements();
    ASSERT_TRUE(guard.owns_lock());
    std::promise<void> started;
    std::promise<void> finished;
    auto started_future = started.get_future();
    auto finished_future = finished.get_future();
    std::thread worker([&]() {
      started.set_value();
      if (operation == 0) {
        scheduler_cell_metrics metrics{};
        provider.report_metrics(metrics);
      } else if (operation == 1) {
        provider.clear_rlc_metrics();
      } else if (operation == 2) {
        matching_ue_cond_per_sub_list_l conditions;
        std::vector<ue_id_c> ues;
        provider.get_ues_matching_test_conditions(conditions, ues);
      } else {
        meas_type_c type;
        type.set_meas_name().from_string("DRB.UEThpDl");
        std::vector<meas_record_item_c> items;
        provider.get_meas_data(type, {}, {}, {}, items);
      }
      finished.set_value();
    });
    started_future.wait();
    // Bounded scheduling probe; not a race-detector or exhaustive stress test.
    EXPECT_EQ(finished_future.wait_for(std::chrono::milliseconds{50}),
              std::future_status::timeout);
    guard.unlock();
    worker.join();
    EXPECT_EQ(finished_future.wait_for(std::chrono::milliseconds{0}),
              std::future_status::ready);
  }
}

} // namespace
