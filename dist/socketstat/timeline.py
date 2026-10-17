def summarize(rows, start, end):
    """Each reading describes only its minute; never carry a state across gaps.

    Durations are sampled estimates, not exact physical transition times.
    """
    intervals = []

    def append(a, b, state):
        if b <= a:
            return
        if intervals and intervals[-1]['state'] == state and intervals[-1]['end'] == a:
            intervals[-1]['end'] = b
        else:
            intervals.append({'start': a, 'end': b, 'state': state})

    cursor = start
    for row in rows:
        a = max(start, row['scheduled_at'])
        b = min(end, row['scheduled_at'] + 60)
        if b <= cursor or a >= end:
            continue
        append(cursor, a, 'unknown')
        append(max(cursor, a), b, row['state'])
        cursor = b
    append(cursor, end, 'unknown')
    durations = {state: 0 for state in ('online', 'offline', 'unknown')}
    for interval in intervals:
        durations[interval['state']] += interval['end'] - interval['start']
    known = durations['online'] + durations['offline']
    offline = [i for i in intervals if i['state'] == 'offline']
    return {
        'intervals': intervals,
        'stats': {
            'seconds': durations,
            'availability_percent': round(durations['online'] / known * 100, 2) if known else None,
            'coverage_percent': round(known / (end - start) * 100, 2),
            'offline_intervals': len(offline),
            'longest_offline_seconds': max((i['end'] - i['start'] for i in offline), default=0),
        },
    }
