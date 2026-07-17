"""Sanitize + merge refined email chunk outputs into data/written.json.
Strips em/en dashes (house style rule) deterministically, fixes encoding artefacts."""
import json, os, re, sys

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else 'data/refine_out'
DEST = sys.argv[2] if len(sys.argv) > 2 else 'data/written.json'


def clean(t):
    if not isinstance(t, str):
        return t
    # em/en dash (with optional surrounding spaces) -> comma pause
    t = re.sub(r'\s*[—–]\s*', ', ', t)
    # drop any mojibake replacement characters
    t = t.replace('�', '')
    # remove the banned "I came across" phrasing
    t = t.replace('I came across', 'I noticed').replace('i came across', 'I noticed')
    # collapse accidental double punctuation from the swap
    t = re.sub(r',\s*,', ', ', t)
    t = re.sub(r',\s*([.:!?])', r'\1', t)
    t = re.sub(r'[ \t]{2,}', ' ', t)
    return t


def clean_entry(e):
    for k in ('outreach_subject', 'outreach_draft', 'trigger', 'contact_email'):
        if k in e:
            e[k] = clean(e[k])
    for v in e.get('variants', []):
        for k in ('subject', 'body'):
            if k in v:
                v[k] = clean(v[k])
    for p in e.get('linkedin_profiles', []):
        for k in ('connection_note', 'follow_up_message'):
            if k in p:
                p[k] = clean(p[k])
        p['engagement_suggestions'] = [clean(s) for s in p.get('engagement_suggestions', [])]
    return e


def main():
    # existing contact emails from the live DB, to backfill empty ones
    existing = {}
    try:
        for p in json.load(open('data/prospects.json', encoding='utf-8')):
            email = (p.get('contact_email') or p.get('contact_page_email') or '').strip()
            if p.get('id') and email:
                existing[p['id']] = email
    except Exception:
        pass

    entries, bad = [], []
    for f in sorted(os.listdir(OUT_DIR)):
        if not f.endswith('.json'):
            continue
        try:
            d = json.load(open(os.path.join(OUT_DIR, f), encoding='utf-8'))
            entries += [clean_entry(e) for e in d]
        except Exception as ex:
            bad.append((f, str(ex)))
    by_id = {e['id']: e for e in entries if e.get('id')}
    merged = list(by_id.values())
    backfilled = 0
    for e in merged:
        if not (e.get('contact_email') or '').strip() and existing.get(e['id']):
            e['contact_email'] = existing[e['id']]
            backfilled += 1
    print(f'backfilled contact_email on {backfilled} leads from existing data')
    with open(DEST, 'w', encoding='utf-8') as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    dash = sum(1 for e in merged for v in e.get('variants', [])
               if '—' in v.get('body', '') or '–' in v.get('body', ''))
    print(f'merged {len(merged)} leads -> {DEST}')
    print(f'remaining em/en dashes after sweep: {dash}')
    if bad:
        print('BAD FILES:', bad)


if __name__ == '__main__':
    main()
