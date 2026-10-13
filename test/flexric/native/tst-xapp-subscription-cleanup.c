#include "../../../flexric/src/xApp/sync_ui.h"
#include "../../../flexric/src/xApp/pending_event_xapp.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

static void test_early_ack(void)
{
  sync_ui_t sync = {0};
  init_sync_ui(&sync);

  /* A response may arrive before the caller enters its wait. */
  for (int i = 0; i < 3; ++i) {
    signal_sync_ui(&sync);
    cond_wait_sync_ui(&sync, 100);
    assert(!sync.flag_sync);
    assert(!sync.msg_ack);
  }

  free_sync_ui(&sync);
  puts("PASS: early ACK preserved and consumed across repeated waits");
}

static void test_distinct_pending_requests(void)
{
  pending_event_xapp_ds_t ds = {0};
  init_pending_events(&ds);

  pending_event_xapp_t events[4] = {0};
  for (int i = 0; i < 4; ++i) {
    events[i].ev = E42_RIC_SUBSCRIPTION_DELETE_REQUEST_PENDING_EVENT;
    events[i].id.ric_req_id = 10;
    events[i].id.ric_inst_id = 20;
    events[i].id.ran_func_id = 2;
    events[i].wait_ms = 10000;
  }
  events[1].id.ric_req_id = 11;
  events[2].id.ric_inst_id = 21;
  events[3].id.ran_func_id = 142;

  /* These are map keys, not open OS descriptors. */
  const int fds[4] = {101, 102, 103, 104};
  bool active[4] = {true, true, true, true};
  for (int i = 0; i < 4; ++i)
    add_pending_event(&ds, fds[i], &events[i]);
  assert(bi_map_size(&ds.pending) == 4);

  const int order[4] = {2, 0, 3, 1};
  for (int step = 0; step < 4; ++step) {
    int i = order[step];
    if (step % 2 == 0) {
      pending_event_xapp_t lookup = events[i];
      /* Timeout is not part of the request identity. */
      lookup.wait_ms = 1;
      int* removed_fd = rm_pending_event_ev(&ds, &lookup);
      assert(*removed_fd == fds[i]);
      free(removed_fd);
    } else {
      rm_pending_event_fd(&ds, fds[i]);
    }
    active[i] = false;
    assert(bi_map_size(&ds.pending) == (size_t)(3 - step));
    for (int j = 0; j < 4; ++j) {
      assert(find_pending_event_fd(&ds, fds[j]) == active[j]);
      assert(find_pending_event_ev(&ds, &events[j]) == active[j]);
    }
  }

  free_pending_events(&ds);
  puts("PASS: same-type pending requests remain independently removable");
}

int main(void)
{
  test_early_ack();
  test_distinct_pending_requests();
  return 0;
}
