#ifndef XAPP_SUBSCRIPTION_REQUEST_COPY_H
#define XAPP_SUBSCRIPTION_REQUEST_COPY_H

#include <assert.h>
#include <stdlib.h>
#include <string.h>

#if defined(E2AP_V1)
#include "../../../flexric/src/lib/e2ap/v1_01/e2ap_types/ric_subscription_request.h"
#elif defined(E2AP_V2)
#include "../../../flexric/src/lib/e2ap/v2_03/e2ap_types/ric_subscription_request.h"
#elif defined(E2AP_V3)
#include "../../../flexric/src/lib/e2ap/v3_01/e2ap_types/ric_subscription_request.h"
#else
#error "Unsupported E2AP version"
#endif

/* The returned request owns every allocated field independently. */
static inline ric_subscription_request_t
copy_subscription_request_xapp(const ric_subscription_request_t* src)
{
  assert(src != NULL);
  ric_subscription_request_t dst = {
    .ric_id = src->ric_id,
    .event_trigger = copy_byte_array(src->event_trigger),
    .len_action = src->len_action,
  };

  if (dst.len_action != 0) {
    assert(src->action != NULL);
    dst.action = calloc(dst.len_action, sizeof(*dst.action));
    assert(dst.action != NULL);
  }

  for (size_t i = 0; i < dst.len_action; ++i) {
    const ric_action_t* from = &src->action[i];
    ric_action_t* to = &dst.action[i];
    to->id = from->id;
    to->type = from->type;

    if (from->definition != NULL) {
      to->definition = malloc(sizeof(*to->definition));
      assert(to->definition != NULL);
      *to->definition = copy_byte_array(*from->definition);
    }

    if (from->subseq_action != NULL) {
      to->subseq_action = malloc(sizeof(*to->subseq_action));
      assert(to->subseq_action != NULL);
      *to->subseq_action = *from->subseq_action;
      to->subseq_action->time_to_wait_ms = NULL;
      if (from->subseq_action->time_to_wait_ms != NULL) {
        to->subseq_action->time_to_wait_ms =
          malloc(sizeof(*to->subseq_action->time_to_wait_ms));
        assert(to->subseq_action->time_to_wait_ms != NULL);
        *to->subseq_action->time_to_wait_ms =
          *from->subseq_action->time_to_wait_ms;
      }
    }
  }
  return dst;
}

static inline void
free_saved_subscription_request_xapp(ric_subscription_request_t* request)
{
  assert(request != NULL);
  free_byte_array(request->event_trigger);
  for (size_t i = 0; i < request->len_action; ++i) {
    ric_action_t* action = &request->action[i];
    if (action->definition != NULL) {
      free_byte_array(*action->definition);
      free(action->definition);
    }
    if (action->subseq_action != NULL) {
      free(action->subseq_action->time_to_wait_ms);
      free(action->subseq_action);
    }
  }
  free(request->action);
  memset(request, 0, sizeof(*request));
}

#endif
