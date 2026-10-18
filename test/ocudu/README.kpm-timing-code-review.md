# OCUDU one-second KPM monitoring: read-only code review

## 1. Scope, provenance, and working tree

This report documents the read-only review performed on 2026-10-16 and the subsequent report preparation. It covers DU E2 report timing, the DU clock, KPM Style 4, DRB.UEThpDl/Ul production and storage, getter contracts, UE/subscription/connection lifetime, and possible report latency. No source changes, patches, builds, tests, container actions, shared-service operations, or Git staging/commits/pushes were performed. Only this report is added by this report-saving task.

Repository: `/home/limx59/Work/oai-5gc-pi-review`.

- Repository HEAD: `b14f2745002565d9e44560638bf618470bde6532`.
- Latest repository commit affecting `ocudu/`: `913f15cec5d551c69bcb4f2167751435f10cfb32` (vendoring commit).
- `ocudu/` has no independent `.git`; `git -C ocudu rev-parse HEAD` resolves to the parent repository, not an upstream OCUDU commit.
- Declared upstream OCUDU revision: `440cdbbee077e97e824db285bf227c15c84bd0bb`, from `docker/ocudu/Dockerfile:58-59`. This is a provenance declaration, not an independently verified byte-for-byte match to upstream or to a running binary.
- Scoped working-tree status for `ocudu/` before saving: `clean` (no entries).
- The parent working tree already contained the following untracked paths before this report was created; no tracked changes were reported:

```text
?? docker/ocudu/Dockerfile.zmq-poll-yield-test
?? docker/ocudu/Dockerfile.zmq-poll-yield-test.dockerignore
?? flexric/build-local/
?? flexric/compile_commands.json
?? test/flexric/__pycache__/
?? test/ocudu/patches/compose.kpm-timing-cpu-shared-test.yaml
?? test/ocudu/patches/compose.kpm-timing-cpu-test.yaml
?? test/ocudu/patches/compose.kpm-timing-poll-yield-test.yaml
?? test/ocudu/patches/patch-ocudu-zmq-poll-yield.py
?? test/ocudu/validate-zmq-kpm-timing.py
?? test/xapp/__pycache__/
?? third_party/uhd/build-local/
```

All source references below use repository-relative paths and the line numbering observed during this review. **Fact** means supported by local source inspection. **Hypothesis** means a possible runtime consequence requiring measurement or reproduction. **Recommendation** means proposed future work, not an implemented or validated change.

## 2. Executive assessment

**Fact:** The current implementation does not guarantee one fresh, valid measurement covering each consecutive wall-clock second. E2 uses DU timers, samples the provider after each report wait, and reads retained RLC statistics without a freshness check. The next relative wait begins after processing the current report. Evidence: `ocudu/lib/du/du_high/o_du_high_factory.cpp:195-201`; `ocudu/lib/e2/procedures/e2ap_indication_procedure.cpp:24-87`; `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:148-154,693-818`.

**Fact:** Important correctness gaps precede timing optimization: Style 4 ignores getter success and output size before indexing; readiness does not establish valid or fresh data; message cleanup changes the header timestamp before header encoding. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:79-100,361-373,421-452`; `ocudu/lib/e2/procedures/e2ap_indication_procedure.cpp:57-61`.

**Interpretation:** Sending every second, receiving every second, producing a new sample every second, and measuring a wall-clock one-second window are four different properties. The reviewed path does not make them equivalent.

## 3. Timer and report call chains

### 3.1 E2 and DU clock

| Step | Evidence |
|---|---|
| gNB creates the DU clock controller | `ocudu/apps/gnb/gnb.cpp:404-405` |
| O-DU factory supplies the controller's timer manager and DU E2 executor to E2 | `ocudu/lib/du/du_high/o_du_high_factory.cpp:195-201` |
| DU E2 factory forwards timer/executor dependencies | `ocudu/lib/e2/common/e2_du_factory.cpp:24-29` |
| E2 entity constructs E2AP; E2AP creates its event manager with those timers | `ocudu/lib/e2/common/e2_entity.cpp:39-45`; `ocudu/lib/e2/common/e2_impl.cpp:18-27` |
| Subscription setup extracts event-trigger report period | `ocudu/lib/e2/common/e2_subscription_manager_impl.cpp:43-45` |
| Subscription setup creates a delete-event source and starts indication processing | `ocudu/lib/e2/procedures/e2ap_subscription_setup_procedure.cpp:35-37` |
| Indication coroutine subscribes with a report-period timeout and awaits it | `ocudu/lib/e2/procedures/e2ap_indication_procedure.cpp:32-35` |

**Fact:** The clock source switches to cell-driven operation when the first cell activates and returns to wall-clock operation when all cells deactivate. Manual ticks are queued on the timer-source executor; unsuccessful dispatch accumulates missed ticks. Evidence: `ocudu/lib/du/du_high/du_high_clock_controller_factory.cpp:55-90`.

**Fact:** Active-cell clock advancement follows slot indications at subframe boundaries. The controller computes skipped subframes; a jump of at least 128 subframes is rejected at that update. Evidence: `ocudu/lib/du/du_high/du_high_clock_controller_factory.cpp:161-206`.

**Interpretation:** During active-cell operation, a 1000 ms timer depends on approximately 1000 radio subframe ticks. It is not an independent guarantee of a wall-clock second. Slow or stalled radio progress can delay expiry; the magnitude in the deployed system is unmeasured.

### 3.2 Style 4 report chain

`report timeout -> collect_measurements() -> enumerate matching UEs -> get_meas_data() for each requested metric -> throughput getter -> is_ind_msg_ready() -> KPM message encoding/cleanup -> header encoding -> E2 indication -> E2AP encoding -> SCTP`.

Evidence: `ocudu/lib/e2/procedures/e2ap_indication_procedure.cpp:53-99`; `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:376-457`; `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:276-290`; `ocudu/lib/e2/gateways/e2_network_client_factory.cpp:68-84`.

**Fact:** Style 4 stores `granul_period` and places it in report metadata, but this path has no separate granularity-period collection timer. The indication coroutine collects once per report wake and immediately encodes a ready report. Normally this yields one measurement-data row per UE per emitted report, not automatically `report_period / granul_period` rows. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:55-65,346-357,393,436-456`; `ocudu/lib/e2/procedures/e2ap_indication_procedure.cpp:57-61`.

**Fact:** No matching UE means collection returns false and readiness remains false; the readiness accessor clears unready report state. Any nonempty UE report list sets readiness true before getter results are inspected. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:69-76,421-427`.

## 4. Throughput production, update period, cache, and reads

### 4.1 Production chain

`RLC PDU processing -> byte counters -> periodic get_and_reset_metrics() -> TX-high/TX-low/RX collector -> application metrics producer/callback/consumer -> E2 metrics connector -> DU measurement provider`.

| Property | Fact and evidence |
|---|---|
| DL byte production | New/segmented PDU paths update counters; examples: `ocudu/lib/rlc/rlc_tx_am_entity.cpp:348,412,511`; `ocudu/lib/rlc/rlc_tx_um_entity.cpp:251-253` |
| UL byte production | Receive paths increment PDU bytes; examples: `ocudu/lib/rlc/rlc_rx_am_entity.cpp:80`; `ocudu/lib/rlc/rlc_rx_um_entity.cpp:43` |
| Periodic counter snapshots | TX high/low and RX timers take and reset metrics, then rearm: `ocudu/lib/rlc/rlc_tx_entity.h:53-65`; `ocudu/lib/rlc/rlc_rx_entity.h:37-42` |
| Configured update period | RLC configuration takes `du_report_period` when RLC metrics are enabled: `ocudu/apps/units/flexible_o_du/o_du_high/du_high/du_high_config_translators.cpp:1321-1322`; lab configuration enables RLC and sets 1000: `deploy/ocudu/config/gnb-zmq-e2.yml:87-92` |
| Collector alignment | TX-high, TX-low, and RX counters must match before reporting; tasks use the UE executor, and failed dispatch is logged: `ocudu/lib/rlc/rlc_bearer_metrics_collector.cpp:30-78` |
| Application forwarding | Factory connects the producer and E2 consumer; callback defers consumers: `ocudu/apps/units/flexible_o_du/o_du_high/o_du_high_unit_factory.cpp:128-135,255-259`; `ocudu/apps/units/flexible_o_du/o_du_high/du_high/metrics/du_high_rlc_metrics.h:40-52`; `ocudu/apps/units/flexible_o_du/o_du_high/du_high/metrics/du_high_rlc_metrics_consumers.cpp:41` |
| Provider update | Connector calls provider directly: `ocudu/lib/e2/common/e2_du_metrics_connector.cpp:20-24` |

The configured period is not proof that fresh merged statistics arrive every wall-clock second. Timer progress, callback execution, collector alignment, and forwarding are separate stages.

### 4.2 Cache and formula semantics

**Fact:** RLC reports are appended to a queue keyed only by UE index. The oldest entry is removed when the configured maximum is exceeded. The default maximum is one, and the production factory uses the default constructor. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:148-154`; `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.h:117`; `ocudu/lib/e2/common/e2_du_factory.cpp:39`.

**Fact:** DL throughput averages unsegmented and segmented PDU-byte counts over queued reports, converts bytes to kbits, and divides by the last entry's configured `metrics_period`. UL averages RX PDU bytes and divides by that configured period. Integer averaging can truncate byte counts. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:693-736,766-791`.

**Fact:** Reads do not consume cached reports and perform no sample-age or sample-version validation. Requested UE IDs are mapped back to UE indices; missing entries produce `no_value` in the normal nonempty-cache path. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:749-763,804-818`.

**Interpretation:** With the default one-entry queue, this is effectively the latest arriving bearer report for a UE. Multiple DRBs can overwrite one another's retained statistics; it is not a guaranteed sum across that UE's DRBs. Increasing queue length alone creates an average over mixed reports, not a correct per-window bearer sum. The keying and averaging evidence above establishes this limitation.

**Hypothesis:** If actual counter intervals stretch beyond the configured period, dividing by the configured period can distort wall-clock throughput. Measure actual interval boundaries before quantifying the bias.

### 4.3 Cleanup

**Fact:** Report cleanup clears Style 4 output lists, row count, and readiness; it does not clear provider history. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:361-373`.

**Fact:** Provider cleanup runs on scheduler-metric arrival, only when more than 1000 ms of `system_clock` time has elapsed since its previous check. It removes entries whose DU F1AP identity is invalid. It does not expire old data belonging to still-valid UEs, and it has no autonomous cleanup trigger when scheduler reports stop. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:134-178`.

**Hypothesis:** System-clock adjustments can alter cleanup-check timing. A monotonic age clock would avoid this dependency; no clock-adjustment experiment was performed.

## 5. Freshness, return values, record counts, and lifetime

### 5.1 Getter contract and unchecked indexing — high priority

**Fact:** `get_meas_data()` dispatches to a metric getter without enforcing a common output cardinality. Style 4 discards its boolean return and indexes the output for every UE. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:276-290`; `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:436-452`.

| Getter path | Return/output contract observed |
|---|---|
| Supported throughput, nonempty cache, accepted labels | One numeric or `no_value` record per requested UE; true |
| Unsupported metric | False, no appended record |
| Empty cache with nonempty requested UE list | False, no appended record |
| Rejected throughput label list | False, no appended record |
| Empty cache with no requested UEs (node-level request) | One placeholder, including zero for real-valued metrics; true |

Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:284-286,293-314,699-705,749-763,772-778,804-818`.

**Static defect:** The caller's unchecked indexing is unsafe when a getter supplies fewer records. A concrete admission mismatch is multiple `NO_LABEL` entries: admission checks each label separately, while throughput getters reject lists longer than one. This yields an empty result that Style 4 indexes when UEs are present. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_impl.cpp:64-75`; provider `:702-705,775-778`; report service `:447,452`. This trigger is established by source analysis, not a runtime reproduction.

### 5.2 Readiness and timestamp integrity

**Fact:** Nonempty UE membership is sufficient for Style 4 readiness, even without a freshness or valid-value check. Matching-condition evaluation currently returns all cached UEs with a valid CU F1AP mapping rather than implementing the requested predicates. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:421-427`; `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:254-273`.

**Static defect:** Message serialization invokes cleanup, cleanup overwrites `collet_start_time`, and only then does the indication procedure serialize the header. Thus the transmitted timestamp reflects cleanup after message packing rather than a reliable start boundary for that message's measurement window. Evidence: `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:79-100,366-367`; `ocudu/lib/e2/procedures/e2ap_indication_procedure.cpp:60-61`.

### 5.3 UE deletion and reuse

**Fact:** Invalid CU mappings are skipped during matching; cached entries are removed later by scheduler-triggered cleanup. Evidence: provider `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:157-178,259-263`.

**Hypothesis:** UE-index reuse before cleanup and before new statistics arrive can associate retained data with a new UE mapping. Validate deletion/recreation timing and identity generation; this review does not claim that reuse was observed.

### 5.4 Subscription deletion and disconnection

**Fact:** Subscription deletion sets the delete event, checks `await_ready()`, and erases the subscription. `await_ready()` is a nonblocking completion query, not a wait or cancellation operation, and the result is ignored. Global subscription `stop()` likewise checks readiness and clears the map. Evidence: `ocudu/lib/e2/common/e2_subscription_manager_impl.cpp:19-24,115-122`; `ocudu/include/ocudu/support/async/detail/base_task.h:53`.

**Static behavior:** After a delete event resumes the indication coroutine, it sets `running=false` but still executes the action loop. A final collection/send can therefore occur before the delete response when data is ready. Evidence: `ocudu/lib/e2/procedures/e2ap_indication_procedure.cpp:36-40,57-86`; `ocudu/lib/e2/procedures/e2ap_subscription_delete_procedure.cpp:35-37`.

**Fact:** Delete-event sources are inserted/replaced by request ID; no corresponding erase/clear was found in the reviewed deletion paths. Distinct IDs can retain event-map entries until the event manager is destroyed. Evidence: `ocudu/include/ocudu/e2/e2_event_manager.h:20-29`; `ocudu/lib/e2/common/e2_subscription_manager_impl.cpp:115-122`.

Disconnect chain: `RX channel destruction -> queued connection-loss handling -> agent notification -> connection-loss routine -> subscription manager stop -> reconnect`. Evidence: `ocudu/lib/e2/common/e2_connection_handler.cpp:27-30,111-140`; `ocudu/lib/e2/common/e2_entity.cpp:113-127`; `ocudu/lib/e2/procedures/ric_connection_loss_routine.cpp:20`.

**Fact:** These paths clear subscriptions without rebuilding the DU metrics provider. Reconnection/resubscription alone does not certify fresh data. Evidence: disconnect chain above and provider creation/ownership transfer at `ocudu/lib/e2/common/e2_du_factory.cpp:39-44`.

**Open check:** Suspended coroutine destruction, event unsubscription, timer invalidation, and already-queued callback lifetime need a deeper cancellation audit and isolated runtime validation. A nonblocking `await_ready()` call alone neither proves graceful completion nor proves a use-after-free.

### 5.5 Concurrency — high-priority risk

**Fact:** Application metrics use a metrics strand, E2 uses the DU control strand, and the connector directly invokes provider methods. The inspected provider methods do not show locking or snapshot publication around shared caches. Evidence: `ocudu/apps/gnb/gnb.cpp:576-582`; `ocudu/apps/services/worker_manager/worker_manager.cpp:378-387`; `ocudu/lib/du/du_high/du_high_executor_mapper.cpp:411-423`; `ocudu/lib/e2/common/e2_du_metrics_connector.cpp:12-24`; provider `:134-178,709-736,783-791`.

**Hypothesis:** Concurrent updates/cleanup and reads can race on the cache or produce DL/UL values from different versions. Reproduction and a complete executor/lifetime audit remain outstanding; no race detector was run.

## 6. Why actual report gaps can exceed one second

The following are confirmed mechanisms, not measured attribution of the historical gaps.

| Confirmed mechanism | Possible effect and source evidence |
|---|---|
| Active-cell timer follows radio progress | Slow/stalled radio progress delays report expiry: `ocudu/lib/du/du_high/du_high_clock_controller_factory.cpp:55-90,161-206` |
| Relative wait is rearmed after work | Collection, encoding, copying, and notifier work precede the next wait; there is no absolute periodic deadline: `ocudu/lib/e2/procedures/e2ap_indication_procedure.cpp:24-87` |
| Tick dispatch and timeout callback dispatch are queued | Missed ticks accumulate; failed timeout dispatch retries later: clock controller `:77-90`; `ocudu/lib/support/timers.cpp:486-543` |
| E2 shares the DU control strand | Control work can delay E2 execution: `ocudu/lib/du/du_high/du_high_executor_mapper.cpp:411-423` |
| RLC snapshots require alignment and forwarding | Delayed/dropped producer tasks can delay cache renewal: `ocudu/lib/rlc/rlc_bearer_metrics_collector.cpp:30-78`; `ocudu/apps/units/flexible_o_du/o_du_high/du_high/metrics/du_high_rlc_metrics.h:47-52` |
| No matching UE means no report | Readiness/collection suppression can enlarge receive gaps: report service `:69-76,421-423`; indication procedure `:58-64` |
| Two serialization layers and copies | KPM packing, message/header copies, and E2AP packing add work: report service `:79-100`; indication procedure `:75-84`; `ocudu/lib/e2/gateways/e2_network_client_factory.cpp:68-84` |
| Failure can lose the current report | KPM packing failure still clears collected output; later buffer resizing or outer packing failure can drop it: report service `:83-87`; indication procedure `:75-82`; network client `:73-75` |

**Historical evidence only:** `test/ocudu/README.zmq-kpm.md:223-225` reports approximately 1.2–4.6-second receive gaps. This review did not rerun those measurements or establish their cause.

**Unverified hypotheses:** Raspberry Pi CPU saturation, thermal throttling, ZeroMQ polling behavior, worker contention, scheduler delays, logging overhead, SCTP/network delay, and receiver processing may contribute. The existence of local CPU/polling experiment files is not evidence that an optimization works. No quantitative benefit is claimed.

## 7. Prioritized recommendations for Raspberry Pi

All entries are recommendations for separately authorized future work. None was implemented or tested here.

| Priority | Recommendation and evidence motivating it | Expected benefit | Risk/tradeoff | Validation method |
|---|---|---|---|---|
| P0 | Enforce one output per requested UE, handle getter failure, and align label admission with getters (Section 5.1) | Prevent out-of-bounds reads and malformed rows | Incorrect fallback could hide errors as valid zero | Isolated cases for duplicate labels, missing UE/cache, failed getter, and mixed valid/no-value rows; verify exact column alignment |
| P0 | Serialize provider reads/updates or publish bounded immutable snapshots; capture one version for both metrics (Section 5.5) | Eliminate shared-cache race risk and mixed-version reports | Lock contention, snapshot-copy cost, or added queue latency | Audit executor ownership; isolated race detection; compare source/report versions and queue latency |
| P1 | Add sample identity, production boundaries, age, and UE lifecycle generation; aggregate per bearer then per UE (Sections 4–5) | Make freshness and correct UE totals observable | More state and aggregation cost; revised aggregation semantics | Dual-DRB traffic, UE deletion/reuse, idle/active transitions, and known byte counts |
| P1 | Define whether the product promises latest-value delivery or new one-second windows; if needed, use a separate monotonic absolute-deadline report scheduler (Sections 3, 8) | Reduce cumulative scheduling drift and clarify guarantees | Duplicate latest values or changed window meaning unless producer semantics are addressed | Slow/pause/resume radio progress; compare scheduled/actual deadlines, missed periods, and source versions |
| P1 | Exit immediately on deletion; retire event entries; specify cancellation and disconnected-cache policy (Section 5.4) | Avoid final unwanted reports and retained control state | Callback/lifetime changes can introduce cancellation bugs | Delete/disconnect while waiting and with callbacks queued; repeated unique subscriptions; inspect retained state |
| P1 | Preserve the correct measurement timestamp through message/header encoding; make packing failure explicit (Section 5.2 and Section 6) | Trustworthy timestamps and visible report loss | Timestamp changes may affect consumers | Decode both layers; compare timestamp with actual sample boundaries and failed-pack behavior |
| P2 | Reuse bounded buffers, compute both rates once per snapshot, and avoid repeated all-UE scans/maps (Section 4.2) | Lower allocation, copying, and CPU work | Stale derived caches or excessive retained memory | Compare CPU time, allocations, RSS, encoding cost, and p95/p99 latency at fixed UE/metric counts |
| P2 | Measure worker contention and logging cost before tuning threads/affinity; avoid relying on larger queues (Section 6) | Better tail latency within Pi CPU/thermal limits | Extra threads can compete with radio work; larger queues can hide overload | Matched-load comparisons of temperature/frequency, CPU, queue depth/wait, radio-to-wall progress, and end-to-end latency |

A useful future measurement record should include monotonic time, radio subframe time, RLC counter/sample identity, UE generation/bearer, actual interval boundaries, cache-update time, scheduled/actual timer firing, queue delay, collection cost, KPM/E2AP encoding cost, send time, and receiver time. Equal consecutive numeric values alone do not prove reuse: legitimate independent idle samples can both be zero.

## 8. Wall-clock scheduling and measurement-window semantics

**Fact-derived assessment:** Changing only E2 report scheduling does not reset or consume provider history and does not redefine RLC production intervals. A faster wall-clock report loop can read the same cached sample repeatedly while radio-driven production advances slowly. It can also skip intermediate samples because the default cache retains one entry. Evidence: timer dependency in Section 3; provider retention and non-consuming getter paths in Section 4.

**Recommendation:** If the requirement is “send the latest available value every second,” explicitly identify stale/reused values. If it is “obtain one new valid measurement for each wall-clock second,” align producer boundaries, denominator, aggregation, and freshness policy with that requirement. These are distinct contracts.

**Semantic risk:** Moving the producer's timing as well as the sender's timing changes what interval counters describe. Normalizing with measured wall elapsed time instead of the configured radio interval also changes the throughput definition. Such changes require an explicit decision and reference measurements, not just a cadence improvement. Evidence for the current denominator: provider `ocudu/lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:734-736,789-791`.

**Fact-derived limit:** Replaying several overdue reports cannot reconstruct missing one-second windows from the current one-entry cache. Repeatedly reading the latest value manufactures repeated observations rather than recovered historical windows.

## 9. Evidence limits and outstanding work

- This is static source review. No tests, profiling, race detection, packet capture, binary inspection, deployment checks, or service actions were performed.
- The upstream revision is declared by local packaging metadata; the reviewed vendored tree and a running image were not independently matched to that revision (Section 1).
- Historical receive gaps are documented evidence, not measurements produced by this review; no unique root cause or numerical optimization gain is established (Section 6).
- Getter/cardinality and timestamp findings are source-level defects. Exact crash behavior and downstream consumer effects were not reproduced (Sections 5.1–5.2).
- Concurrency, UE-index reuse, timer/coroutine cancellation, queued callback lifetime, and system-clock adjustment effects require further audit and isolated experiments (Section 5).
- Precise metric conformance to external O-RAN/3GPP definitions and all RLC modes/bearer combinations was not independently certified; the report describes the local implementation.
- Required next evidence: source-to-binary provenance; per-stage timing with source-sample identities; multiple-bearer accounting; deletion/disconnect/reconnect stress; and Pi-specific CPU/thermal/queue measurements. Each requires separate authorization. The current deliverable contains recommendations only, with no implementation or patch.
