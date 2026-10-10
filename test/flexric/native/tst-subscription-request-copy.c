#include "subscription_request_copy.h"
#include <stdio.h>

int main(void)
{
  ric_subscription_request_t original = {0};
  original.ric_id.ric_req_id = 10;
  original.ric_id.ric_inst_id = 20;
  original.ric_id.ran_func_id = 2;
  original.event_trigger.len = 3;
  original.event_trigger.buf = malloc(3);
  assert(original.event_trigger.buf != NULL);
  memcpy(original.event_trigger.buf, "abc", 3);

  original.len_action = 2;
  original.action = calloc(2, sizeof(*original.action));
  assert(original.action != NULL);
  original.action[0].id = 1;
  original.action[0].type = 0;
  original.action[0].definition =
    calloc(1, sizeof(*original.action[0].definition));
  assert(original.action[0].definition != NULL);
  original.action[0].definition->len = 3;
  original.action[0].definition->buf = malloc(3);
  assert(original.action[0].definition->buf != NULL);
  memcpy(original.action[0].definition->buf, "xyz", 3);

  original.action[0].subseq_action =
    calloc(1, sizeof(*original.action[0].subseq_action));
  assert(original.action[0].subseq_action != NULL);
  original.action[0].subseq_action->time_to_wait_ms =
    malloc(sizeof(*original.action[0].subseq_action->time_to_wait_ms));
  assert(original.action[0].subseq_action->time_to_wait_ms != NULL);
  *original.action[0].subseq_action->time_to_wait_ms = 100;

  /* The second action deliberately has no optional fields. */
  original.action[1].id = 2;
  original.action[1].type = 0;

  ric_subscription_request_t saved =
    copy_subscription_request_xapp(&original);

  assert(saved.event_trigger.buf != original.event_trigger.buf);
  assert(saved.action != original.action);
  assert(saved.action[0].definition != original.action[0].definition);
  assert(saved.action[0].definition->buf !=
         original.action[0].definition->buf);
  assert(saved.action[0].subseq_action != original.action[0].subseq_action);
  assert(saved.action[0].subseq_action->time_to_wait_ms !=
         original.action[0].subseq_action->time_to_wait_ms);

  original.event_trigger.buf[0] = '!';
  original.action[0].definition->buf[0] = '!';
  *original.action[0].subseq_action->time_to_wait_ms = 200;
  free_saved_subscription_request_xapp(&original);

  assert(saved.ric_id.ric_req_id == 10);
  assert(saved.ric_id.ric_inst_id == 20);
  assert(saved.ric_id.ran_func_id == 2);
  assert(saved.event_trigger.len == 3);
  assert(memcmp(saved.event_trigger.buf, "abc", 3) == 0);
  assert(saved.len_action == 2);
  assert(saved.action[0].id == 1);
  assert(saved.action[0].definition->len == 3);
  assert(memcmp(saved.action[0].definition->buf, "xyz", 3) == 0);
  assert(*saved.action[0].subseq_action->time_to_wait_ms == 100);
  assert(saved.action[1].id == 2);
  assert(saved.action[1].definition == NULL);
  assert(saved.action[1].subseq_action == NULL);

  free_saved_subscription_request_xapp(&saved);
  assert(saved.action == NULL);
  assert(saved.len_action == 0);
  assert(saved.event_trigger.buf == NULL);
  free_saved_subscription_request_xapp(&saved);

  ric_subscription_request_t empty = {0};
  saved = copy_subscription_request_xapp(&empty);
  assert(saved.action == NULL);
  assert(saved.len_action == 0);
  free_saved_subscription_request_xapp(&saved);

  puts("PASS: saved subscription owns independent request fields");
  puts("PASS: optional fields and empty requests can be released safely");
  return 0;
}
