#ifndef OAI_PI_STEERING_MAC_LOAD_H
#define OAI_PI_STEERING_MAC_LOAD_H

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

/* Test capacity: 106 PRBs per 500-us slot; not measured radio capacity.
 * Caller serializes access to each state. */
typedef struct {
  uint64_t last_ns;
  uint64_t remainder;
  uint32_t total_prb;
} steering_mac_load_t;

static inline uint64_t steering_monotonic_ns(void)
{
  struct timespec now;
  int rc = clock_gettime(CLOCK_MONOTONIC, &now);
  assert(rc == 0);
  return (uint64_t)now.tv_sec * 1000000000ULL + now.tv_nsec;
}

static inline unsigned steering_load_percent(void)
{
  const char* path = getenv("STEERING_LOAD_FILE");
  if (path == NULL || path[0] == '\0')
    path = "/tmp/steering-load-percent";
  FILE* file = fopen(path, "r");
  if (file == NULL) {
    fprintf(stderr, "Cannot open steering load file: %s\n", path);
    abort();
  }
  unsigned percent;
  char extra;
  int count = fscanf(file, "%u %c", &percent, &extra);
  fclose(file);
  if (count != 1 || percent > 100) {
    fprintf(stderr, "Steering load must be an integer in 0..100\n");
    abort();
  }
  return percent;
}

static inline uint32_t steering_accumulate_prb(
    steering_mac_load_t* state, uint64_t now_ns, unsigned percent)
{
  assert(state != NULL && percent <= 100);
  if (state->last_ns == 0) {
    state->last_ns = now_ns;
    return state->total_prb;
  }
  assert(now_ns >= state->last_ns);
  uint64_t elapsed = now_ns - state->last_ns;
  state->last_ns = now_ns;
  /* ARM64 GCC supports 128-bit integers: long idle intervals must
   * not overflow the intermediate multiplication or abort the Agent.
   * The MAC wire counter is uint32_t and wraps modulo 2^32. */
  __uint128_t numerator =
      (__uint128_t)elapsed * 106ULL * percent + state->remainder;
  __uint128_t increment = numerator / 50000000ULL;
  state->remainder = (uint64_t)(numerator % 50000000ULL);
  state->total_prb += (uint32_t)increment;
  return state->total_prb;
}

#endif
