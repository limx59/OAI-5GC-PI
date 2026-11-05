#!/usr/bin/env python3
"""Build a live two-node callback using retained recovery validation logic. Fault injection is disabled. Each changed cap requires actual DL evidence."""
import json, re

def make_apply(context):
    GNBS = context['GNBS']
    containers = context['containers']
    logs = context['logs']
    save = context['save']
    project = context['project']
    summary = context['summary']
    invoke = context['invoke']
    CLIENT = context['CLIENT']
    output = context['output']
    ping = context['ping']
    require = context['require']
    attempt_number = 1

    def apply(node, cap, generation):
        label = f'live-generation{generation}'
        service = GNBS[node]
        injected = False
        tag = f'{label}.attempt{attempt_number}.{node}'
        before = logs(containers[service])
        save('gnb.' + tag + '.before.json', before)
        name = project + '-client-' + node
        try:
            summary['control_requests_attempted'] += 1
            result = invoke(['run', '--name', name, '--rm', '--pull=never', '--network', 'none' if injected else 'container:' + containers[service], CLIENT, '--min-ratio', str(cap['min_prb_policy_ratio']), '--max-ratio', str(cap['max_prb_policy_ratio'])], timeout=30)
            save('control.' + tag + '.log', result.stdout + result.stderr)
        finally:
            if output(['ps', '-a', '-q', '--filter', 'name=^/' + name + '$']):
                output(['rm', '-f', name])
        records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        requests = [r for r in records if r.get('event') == 'request']
        replies = [r for r in records if r.get('event') == 'response']
        require(len(requests) == 1, 'Expected one client request')
        if injected:
            errors = [r.get('error', '') for r in records if r.get('passed') is False]
            require(result.returncode != 0 and (not replies) and any(('connection refused' in e.lower() for e in errors)), 'Expected isolated-client connection refusal')
        else:
            require(result.returncode == 0 and len(replies) == 1 and any((r.get('passed') is True for r in records)), 'Unexpected control failure')
            summary['control_replies_validated'] += 1
            probe = invoke([
                "exec", containers["nrue" if node == "420" else "nrue-2"],
                "ping", "-I", "oaitun_ue1",
                "-c", "5", "-i", "1", "-s", "1200", "-W", "5",
                "192.168.100.1",
            ], timeout=40)
            save("ping." + tag + ".log", probe.stdout + probe.stderr)
            require(probe.returncode == 0
                    and "5 received" in probe.stdout
                    and "0% packet loss" in probe.stdout,
                    "Control verification probe failed: " + node)
        after = logs(containers[service])
        save('gnb.' + tag + '.after.json', after)
        require(all((after[k].startswith(before[k]) for k in before)), 'Scheduler history changed')
        delta = '\n'.join((after[k][len(before[k]):] for k in before))
        events = delta.count('- Slice Reconfig: cell=0')
        repeated = False
        require(events == 0 if injected else events in (0, 1) if repeated else events == 1, 'Unexpected scheduler event count')
        dl_check = None
        if not injected:
            header = re.compile('^.*Slot decisions pci=1 .*?\\((\\d+) PDSCHs?, (\\d+) PUSCHs?.*$', re.M)
            grant = re.compile('UE (PDSCH|PUSCH): ue=(\\d+) c-rnti=(0x[0-9a-fA-F]+).*?\\brb=\\[(\\d+)\\.\\.(\\d+)\\).*?\\bnrtx=(\\d+)\\b')
            segment = delta.split('- Slice Reconfig: cell=0', 1)[1] if events else delta
            headers = list(header.finditer(segment))
            totals = []
            parsed = 0
            for i, match in enumerate(headers):
                end = headers[i + 1].start() if i + 1 < len(headers) else len(segment)
                records = grant.findall(segment[match.end():end])
                counts = {direction: sum((r[0] == direction for r in records)) for direction in ('PDSCH', 'PUSCH')}
                require(counts['PDSCH'] == int(match[1]) and counts['PUSCH'] == int(match[2]), 'Incomplete scheduler slot')
                total = 0
                for direction, ue, rnti, low, high, nrtx in records:
                    parsed += 1
                    low, high = (int(low), int(high))
                    require(ue == '0' and rnti.lower() == '0x4601' and (nrtx == '0') and (0 <= low < high <= 51), 'Unexpected grant identity or allocation')
                    if direction == 'PDSCH':
                        total += high - low
                if counts['PDSCH']:
                    totals.append(total)
            require(parsed == len(re.findall('UE (?:PDSCH|PUSCH):', segment)), 'Grant outside parsed slot blocks')
            require(totals, 'Missing actual DL grants')
            if cap['max_prb_policy_ratio'] == 20:
                require(max(totals) <= 10 and 10 in totals, 'Actual DL cap not demonstrated')
            else:
                require(max(totals) > 10, 'Actual DL restoration not demonstrated')
            dl_check = {'active_slots': len(totals), 'max_prbs_per_slot': max(totals), 'slots_above_10': sum((v > 10 for v in totals))}
        return {'verified': not injected, 'fault_injected': injected, 'generation': generation, 'max_ratio': cap['max_prb_policy_ratio'], 'scheduler_events': events, 'same_plan_reapplication': repeated, 'dl_grant_check': dl_check, 'evidence_tag': tag}
    return apply
