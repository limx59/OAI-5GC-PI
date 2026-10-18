// Appended to e2sm_kpm_test.cpp only in the Docker source copy.
namespace {

class style4_guard_meas_provider : public dummy_e2sm_kpm_du_meas_provider
{
public:
  bool fault_enabled = true;
  bool fault_success = false;
  unsigned fault_records = 0;

  bool get_ues_matching_test_conditions(
      const matching_ue_cond_per_sub_list_l& conditions,
      std::vector<ue_id_c>& ues) override
  {
    for (unsigned id : {31U, 47U}) {
      ue_id_c ue;
      ue.set_gnb_du_ue_id() = generate_ueid_gnb_du(id);
      ues.push_back(ue);
    }
    return true;
  }

  bool get_meas_data(const meas_type_c& meas_type,
                     const label_info_list_l labels,
                     const std::vector<ue_id_c>& ues,
                     const std::optional<cgi_c> cell,
                     std::vector<meas_record_item_c>& items) override
  {
    bool second = meas_type.meas_name().to_string() == "second";
    if (second && fault_enabled) {
      for (unsigned i = 0; i != fault_records; ++i) {
        items.emplace_back().set_integer() = 999;
      }
      return fault_success;
    }
    for (unsigned i = 0; i != ues.size(); ++i) {
      items.emplace_back().set_integer() = (second ? 100 : 0) + 42 + i;
    }
    return true;
  }
};

e2sm_kpm_action_definition_s make_style4_guard_action()
{
  e2sm_kpm_action_definition_s action;
  action.ric_style_type = 4;
  auto& format = action.action_definition_formats.set_action_definition_format4();
  format.sub_info.cell_global_id_present = false;
  format.sub_info.granul_period = 1000;
  for (const char* name : {"first", "second"}) {
    meas_info_item_s metric;
    metric.meas_type.set_meas_name().from_string(name);
    label_info_item_s label{};
    label.meas_label.no_label_present = true;
    label.meas_label.no_label = meas_label_s::no_label_opts::true_value;
    metric.label_info_list.push_back(label);
    format.sub_info.meas_info_list.push_back(metric);
  }
  return action;
}

TEST(e2sm_kpm_style4_record_guard, invalid_collection_is_discarded_and_next_collection_recovers)
{
  for (bool success : {false, true}) {
    for (unsigned count : {0U, 1U, 2U, 3U}) {
      if (success && count == 2) {
        continue;
      }
      SCOPED_TRACE(fmt::format("success={} records={}", success, count));
      style4_guard_meas_provider provider;
      provider.fault_success = success;
      provider.fault_records = count;
      e2sm_kpm_report_service_style4 service(make_style4_guard_action(), provider);

      // The first metric succeeds before the second metric fails.
      EXPECT_FALSE(service.collect_measurements());
      EXPECT_FALSE(service.is_ind_msg_ready());

      provider.fault_enabled = false;
      ASSERT_TRUE(service.collect_measurements());
      ASSERT_TRUE(service.is_ind_msg_ready());

      auto bytes = service.get_indication_message();
      e2sm_kpm_ind_msg_s message;
      asn1::cbit_ref reader(bytes);
      ASSERT_EQ(message.unpack(reader), asn1::OCUDUASN_SUCCESS);
      const auto& reports = message.ind_msg_formats.ind_msg_format3().ue_meas_report_list;
      ASSERT_EQ(reports.size(), 2U);
      for (unsigned i = 0; i != reports.size(); ++i) {
        EXPECT_EQ(reports[i].ue_id.gnb_du_ue_id().gnb_cu_ue_f1ap_id,
                  i == 0 ? 31U : 47U);
        const auto& data = reports[i].meas_report.meas_data;
        ASSERT_EQ(data.size(), 1U);
        const auto& records = data[0].meas_record;
        ASSERT_EQ(records.size(), 2U);
        ASSERT_EQ(records[0].type(), meas_record_item_c::types_opts::integer);
        ASSERT_EQ(records[1].type(), meas_record_item_c::types_opts::integer);
        EXPECT_EQ(records[0].integer(), 42 + i);
        EXPECT_EQ(records[1].integer(), 142 + i);
      }
      EXPECT_FALSE(service.is_ind_msg_ready());
    }
  }
}

} // namespace
