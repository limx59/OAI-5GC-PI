// Appended after the existing Style 4 guard tests in a disposable source copy.
namespace {

class style4_freshness_provider : public style4_guard_meas_provider
{
public:
  uint64_t first_revision = 1;
  uint64_t second_revision = 2;

  style4_freshness_provider() { fault_enabled = false; }

  std::optional<std::vector<uint64_t>>
  get_cached_rlc_revisions(const ue_id_c& ue) override
  {
    return std::vector<uint64_t>{
        ue.gnb_du_ue_id().gnb_cu_ue_f1ap_id == 31
            ? first_revision : second_revision};
  }

  bool get_meas_data(const meas_type_c& type,
                     const label_info_list_l labels,
                     const std::vector<ue_id_c>& ues,
                     const std::optional<cgi_c> cell,
                     std::vector<meas_record_item_c>& items) override
  {
    meas_type_c translated;
    translated.set_meas_name().from_string(
        type.meas_name().to_string() == "DRB.UEThpUl" ? "second" : "first");
    return style4_guard_meas_provider::get_meas_data(
        translated, labels, ues, cell, items);
  }
};

e2sm_kpm_action_definition_s make_style4_freshness_action()
{
  auto action = make_style4_guard_action();
  auto& metrics = action.action_definition_formats.action_definition_format4()
                      .sub_info.meas_info_list;
  metrics[0].meas_type.set_meas_name().from_string("DRB.UEThpDl");
  metrics[1].meas_type.set_meas_name().from_string("DRB.UEThpUl");
  return action;
}

void expect_style4_freshness(e2sm_kpm_report_service_style4& service,
                            bool first_fresh, bool second_fresh)
{
  ASSERT_TRUE(service.collect_measurements());
  ASSERT_TRUE(service.is_ind_msg_ready());
  auto bytes = service.get_indication_message();
  e2sm_kpm_ind_msg_s message;
  asn1::cbit_ref reader(bytes);
  ASSERT_EQ(message.unpack(reader), asn1::OCUDUASN_SUCCESS);
  const auto& reports = message.ind_msg_formats.ind_msg_format3().ue_meas_report_list;
  ASSERT_EQ(reports.size(), 2U);
  for (unsigned i = 0; i != reports.size(); ++i) {
    const auto& data = reports[i].meas_report.meas_data;
    ASSERT_EQ(data.size(), 1U);
    ASSERT_EQ(data[0].meas_record.size(), 2U);
    const bool fresh = i == 0 ? first_fresh : second_fresh;
    for (unsigned metric = 0; metric != 2; ++metric) {
      const auto& record = data[0].meas_record[metric];
      if (fresh) {
        ASSERT_EQ(record.type(), meas_record_item_c::types_opts::integer);
        EXPECT_EQ(record.integer(), (metric == 0 ? 42 : 142) + i);
      } else {
        EXPECT_EQ(record.type(), meas_record_item_c::types_opts::no_value);
      }
    }
  }
}

TEST(e2sm_kpm_style4_freshness, duplicate_samples_are_unavailable_and_new_samples_recover)
{
  style4_freshness_provider provider;
  e2sm_kpm_report_service_style4 service(make_style4_freshness_action(), provider);
  expect_style4_freshness(service, true, true);
  expect_style4_freshness(service, false, false);

  provider.first_revision = 3;
  expect_style4_freshness(service, true, false);
  provider.second_revision = 4;
  expect_style4_freshness(service, false, true);
}

TEST(e2sm_kpm_style4_freshness, subscriptions_do_not_consume_each_others_samples)
{
  style4_freshness_provider provider;
  e2sm_kpm_report_service_style4 first(make_style4_freshness_action(), provider);
  e2sm_kpm_report_service_style4 second(make_style4_freshness_action(), provider);
  expect_style4_freshness(first, true, true);
  expect_style4_freshness(second, true, true);
  expect_style4_freshness(first, false, false);
  expect_style4_freshness(second, false, false);

  provider.first_revision = 3;
  provider.second_revision = 4;
  expect_style4_freshness(second, true, true);
  expect_style4_freshness(first, true, true);
}

TEST(e2sm_kpm_style4_freshness, failed_collection_does_not_commit_revisions)
{
  style4_freshness_provider provider;
  e2sm_kpm_report_service_style4 service(make_style4_freshness_action(), provider);
  provider.fault_enabled = true;
  EXPECT_FALSE(service.collect_measurements());
  EXPECT_FALSE(service.is_ind_msg_ready());

  provider.fault_enabled = false;
  expect_style4_freshness(service, true, true);
  expect_style4_freshness(service, false, false);

  provider.first_revision = 0;
  provider.second_revision = 0;
  expect_style4_freshness(service, false, false);
}

} // namespace
