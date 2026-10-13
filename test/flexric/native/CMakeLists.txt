cmake_minimum_required(VERSION 3.18)
project(oai_pi_xapp_regression C)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_EXTENSIONS ON)
find_package(Threads REQUIRED)

get_filename_component(FLEXRIC
  "${CMAKE_CURRENT_SOURCE_DIR}/../../../flexric" ABSOLUTE)

add_executable(test_xapp_subscription_cleanup
  tst-xapp-subscription-cleanup.c
  ${FLEXRIC}/src/xApp/sync_ui.c
  ${FLEXRIC}/src/xApp/pending_event_xapp.c
  ${FLEXRIC}/src/lib/pending_events.c
  ${FLEXRIC}/src/lib/e2ap/v2_03/e2ap_types/common/ric_gen_id.c
  ${FLEXRIC}/src/util/alg_ds/ds/assoc_container/bimap.c
  ${FLEXRIC}/src/util/alg_ds/ds/assoc_container/assoc_rb_tree.c
  ${FLEXRIC}/src/util/alg_ds/ds/assoc_container/assoc_reg.c
  ${FLEXRIC}/src/util/alg_ds/ds/seq_container/seq_arr.c
  ${FLEXRIC}/src/util/alg_ds/ds/seq_container/seq_ring.c
  ${FLEXRIC}/src/util/alg_ds/alg/find.c
  ${FLEXRIC}/src/util/alg_ds/alg/lower_bound.c
  ${FLEXRIC}/src/util/alg_ds/alg/defer.c)

target_compile_definitions(test_xapp_subscription_cleanup PRIVATE E2AP_V2)
target_compile_options(test_xapp_subscription_cleanup PRIVATE -UNDEBUG)
target_link_libraries(test_xapp_subscription_cleanup PRIVATE Threads::Threads)

enable_testing()
add_test(NAME xapp_subscription_cleanup
  COMMAND test_xapp_subscription_cleanup)
set_tests_properties(xapp_subscription_cleanup PROPERTIES TIMEOUT 10)

# Subscription request ownership regression
add_executable(test_subscription_request_copy
  tst-subscription-request-copy.c
  ${FLEXRIC}/src/util/byte_array.c)
target_include_directories(test_subscription_request_copy
  PRIVATE ${FLEXRIC}/src)
target_compile_definitions(test_subscription_request_copy PRIVATE E2AP_V2)
target_compile_options(test_subscription_request_copy PRIVATE -UNDEBUG)
add_test(NAME subscription_request_copy
  COMMAND test_subscription_request_copy)
set_tests_properties(subscription_request_copy PROPERTIES TIMEOUT 10)
