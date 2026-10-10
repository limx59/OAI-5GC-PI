#ifndef OAI_PI_STEERING_MAC_REPORT_H
#define OAI_PI_STEERING_MAC_REPORT_H

#include "steering_mac_load.h"
#include "../../../flexric/src/sm/mac_sm/ie/mac_data_ie.h"
#include <pthread.h>

/* Controlled MAC reports for the emulator experiment.
 * tstamp is monotonic microseconds in this dedicated test implementation.
 * DL and UL use the same configured test capacity and load.
 */
static inline void steering_fill_mac_report(mac_ind_data_t* data)
{
  assert(data != NULL);
  static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
  static steering_mac_load_t state = {0};

  int rc = pthread_mutex_lock(&mutex);
  assert(rc == 0);
  unsigned percent = steering_load_percent();
  uint64_t now = steering_monotonic_ns();
  uint32_t total = steering_accumulate_prb(&state, now, percent);

  data->msg.tstamp = (int64_t)(now / 1000ULL);
  data->msg.len_ue_stats = 1;
  data->msg.ue_stats = calloc(1, sizeof(*data->msg.ue_stats));
  assert(data->msg.ue_stats != NULL);
  data->msg.ue_stats[0].rnti = 1;
  data->msg.ue_stats[0].dl_aggr_prb = total;
  data->msg.ue_stats[0].ul_aggr_prb = total;

  rc = pthread_mutex_unlock(&mutex);
  assert(rc == 0);
}

#endif
