#include "steering_mac_load.h"

int main(void)
{
  steering_mac_load_t full = {0};
  assert(steering_accumulate_prb(&full, 1000000000ULL, 100) == 0);
  assert(steering_accumulate_prb(&full, 1100000000ULL, 100) == 21200);

  steering_mac_load_t changing = {0};
  steering_accumulate_prb(&changing, 1000000000ULL, 90);
  assert(steering_accumulate_prb(&changing, 1100000000ULL, 90) == 19080);
  assert(steering_accumulate_prb(&changing, 1200000000ULL, 20) == 23320);
  assert(steering_accumulate_prb(&changing, 1300000000ULL, 0) == 23320);

  steering_mac_load_t fine = {0};
  steering_accumulate_prb(&fine, 1000000000ULL, 33);
  for (uint64_t i = 1; i <= 1000; ++i)
    steering_accumulate_prb(&fine, 1000000000ULL + i * 100000ULL, 33);
  assert(fine.total_prb == 6996);

  steering_mac_load_t same_time = {0};
  steering_accumulate_prb(&same_time, 1000000000ULL, 50);
  assert(steering_accumulate_prb(&same_time, 1000000000ULL, 50) == 0);

  steering_mac_load_t idle = {0};
  steering_accumulate_prb(&idle, 1000000000ULL, 90);
  assert(steering_accumulate_prb(&idle, 301000000000ULL, 90) == 57240000);
  assert(steering_accumulate_prb(&idle, 301100000000ULL, 90) == 57259080);

  steering_mac_load_t wrap = {0};
  steering_accumulate_prb(&wrap, 1000000000ULL, 100);
  wrap.total_prb = UINT32_MAX - 99;
  assert(steering_accumulate_prb(&wrap, 1100000000ULL, 100) == 21100);

  puts("PASS: full capacity, changing load, fractional accumulation and zero elapsed time");
  return 0;
}
