"""
AI Translation Comparison Pipeline (Claude Edition)
=====================================================
Compare glossary Czech translations against Claude AI results.
Output:
  - corrections.csv      : entries where Claude != glossary (keep as correction patches)
  - validated.csv         : entries where Claude == glossary (removable)
  - comparison_full.csv   : full comparison with match status

Usage:
  set ANTHROPIC_API_KEY=sk-ant-...
  python ai_compare_claude.py --pilot       # 200-entry test
  python ai_compare_claude.py               # full run
  python ai_compare_claude.py --resume      # continue from checkpoint

All logs written to ai_compare_claude.log.
"""

import csv
import re
import time
import sys
import json
import os
import unicodedata
from pathlib import Path
import anthropic

# ── Config ──
INPUT = Path(__file__).resolve().parent.parent / 'processed' / 'TransDict_CSY.csv'
OUT_DIR = Path(__file__).resolve().parent.parent
CHECKPOINT = OUT_DIR / 'translate_checkpoint_claude.json'
LOGFILE = OUT_DIR / 'ai_compare_claude.log'
BATCH_SIZE = 50         # entries per Claude API call
SLEEP_BETWEEN = 0.5     # seconds between API calls
MAX_RETRIES = 3
RETRY_DELAY = 5.0
PILOT_MODE = '--pilot' in sys.argv
PILOT_COUNT = 200
MODEL = 'claude-sonnet-4-20250514'

# ── Logging ──
_logf = open(LOGFILE, 'w', encoding='utf-8')
def log(msg):
    _logf.write(msg + '\n')
    _logf.flush()
    print(msg, flush=True)

# ── Normalization for comparison ──
def normalize_for_compare(s):
    """Normalize a string for fuzzy comparison."""
    s = s.strip().lower()
    s = s.replace('&', '')
    s = unicodedata.normalize('NFC', s)
    s = re.sub(r'\.{2,}$', '', s)
    s = s.rstrip('…')
    s = ' '.join(s.split())
    s = s.rstrip(':')
    return s

def match_level(glossary_cz, ai_cz):
    """
    Compare glossary and AI translations.
    Returns: (level, description)
      0 = exact match
      1 = normalized match (case/punctuation)
      2 = one contains the other
      3 = mismatch
    """
    if glossary_cz == ai_cz:
        return 0, 'exact'
    g_norm = normalize_for_compare(glossary_cz)
    a_norm = normalize_for_compare(ai_cz)
    if g_norm == a_norm:
        return 1, 'normalized'
    if g_norm in a_norm or a_norm in g_norm:
        return 2, 'partial'
    return 3, 'mismatch'

# ── Claude batch translation ──
def translate_batch_claude(client, en_texts):
    """
    Translate a batch of English texts to Czech using Claude.
    Returns list of Czech translations.
    """
    # Build numbered list for clear mapping
    numbered = '\n'.join(f'{i+1}. {text}' for i, text in enumerate(en_texts))

    prompt = f"""You are a professional CAD software translator. Translate each of the following English UI strings to Czech.
These are from ZWCAD (a CAD application similar to AutoCAD). Use standard CAD terminology in Czech.

Rules:
- Translate ONLY the text content, preserve format specifiers (%s, %ls, %d, %1!d!, etc.) and escape sequences (\\n, \\t) as-is
- Preserve & (accelerator keys) in the same position relative to the translated word
- Preserve keyboard shortcuts like \\tCtrl+C as-is
- For command names in ALL CAPS (like ARRAY, LINE, CIRCLE), translate to the Czech command equivalent
- Return ONLY the numbered translations, one per line, matching the input numbering
- Do NOT add explanations or notes

Input:
{numbered}

Output (Czech translations, numbered to match):"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )

    # Parse response
    text = response.content[0].text.strip()
    lines = text.strip().split('\n')

    translations = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Remove numbering: "1. translation" or "1) translation"
        m = re.match(r'^\d+[\.\)]\s*(.+)$', line)
        if m:
            translations.append(m.group(1).strip())
        else:
            translations.append(line)

    # Pad if Claude returned fewer translations
    while len(translations) < len(en_texts):
        translations.append('ERROR_PARSE')

    return translations[:len(en_texts)]

# ── Check API key ──
api_key = os.environ.get('ANTHROPIC_API_KEY', '')
if not api_key:
    log('ERROR: ANTHROPIC_API_KEY environment variable not set.')
    log('Set it with: set ANTHROPIC_API_KEY=sk-ant-...')
    sys.exit(1)

client = anthropic.Anthropic(api_key=api_key)
log(f'Using model: {MODEL}')

# ── Load data ──
log(f'Loading {INPUT}...')
with open(INPUT, 'r', encoding='utf-8-sig') as f:
    reader = csv.reader(f)
    header = next(reader)
    rows = [(en, cz) for en, cz in reader if en.strip()]

total = len(rows)
log(f'Loaded {total} entries')

if PILOT_MODE:
    import random
    random.seed(42)
    indices = sorted(random.sample(range(total), min(PILOT_COUNT, total)))
    rows = [rows[i] for i in indices]
    log(f'Pilot mode: selected {len(rows)} entries')

# ── Resume from checkpoint ──
results = []
start_batch = 0
if '--resume' in sys.argv and CHECKPOINT.exists():
    with open(CHECKPOINT, 'r', encoding='utf-8') as f:
        ckpt = json.load(f)
    results = [tuple(r) for r in ckpt['results']]
    start_batch = ckpt['next_batch']
    log(f'Resumed from checkpoint: {len(results)} done, starting at batch {start_batch}')

# ── Translate in batches ──
errors = 0
total_batches = (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE
log(f'\nTranslating {len(rows)} entries in {total_batches} batches (size={BATCH_SIZE})...')
log(f'Estimated time: ~{total_batches * 3 / 60:.0f} min\n')

for batch_idx in range(start_batch, total_batches):
    start = batch_idx * BATCH_SIZE
    end = min(start + BATCH_SIZE, len(rows))
    batch = rows[start:end]
    en_texts = [en for en, cz in batch]

    ai_translations = None
    for attempt in range(MAX_RETRIES):
        try:
            ai_translations = translate_batch_claude(client, en_texts)
            break
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                log(f'  RETRY {attempt+1}/{MAX_RETRIES} batch {batch_idx+1}: {e}')
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                log(f'  FAILED batch {batch_idx+1}: {e}')

    if ai_translations:
        for j, (en, cz) in enumerate(batch):
            ai_cz = ai_translations[j] if j < len(ai_translations) else 'ERROR'
            level, desc = match_level(cz, ai_cz)
            results.append((en, cz, ai_cz, level, desc))
    else:
        errors += 1
        for en, cz in batch:
            results.append((en, cz, 'ERROR', -1, 'error'))

    # Progress
    processed = end
    pct = processed / len(rows) * 100
    matches = sum(1 for _, _, _, l, _ in results if l <= 1)
    mismatches = sum(1 for _, _, _, l, _ in results if l >= 2)
    log(f'  [{processed:>6}/{len(rows)}] {pct:5.1f}%  matches={matches}  mismatches={mismatches}  errors={errors}  batch {batch_idx+1}/{total_batches}')

    # Checkpoint every 5 batches
    if (batch_idx + 1) % 5 == 0:
        with open(CHECKPOINT, 'w', encoding='utf-8') as f:
            json.dump({'next_batch': batch_idx + 1, 'results': results}, f, ensure_ascii=False)

    # Rate limit
    time.sleep(SLEEP_BETWEEN)

# ── Final checkpoint ──
with open(CHECKPOINT, 'w', encoding='utf-8') as f:
    json.dump({'next_batch': total_batches, 'results': results}, f, ensure_ascii=False)

# ── Statistics ──
log(f'\n{"="*60}')
log('RESULTS SUMMARY')
log(f'{"="*60}')

level_counts = {}
for _, _, _, level, desc in results:
    level_counts[desc] = level_counts.get(desc, 0) + 1

for desc in ['exact', 'normalized', 'partial', 'mismatch', 'error']:
    count = level_counts.get(desc, 0)
    pct = count / len(results) * 100 if results else 0
    label = {
        'exact': 'Exact match (Claude == Glossary)',
        'normalized': 'Normalized match (case/punct diff)',
        'partial': 'Partial match (containment)',
        'mismatch': 'Mismatch (Claude != Glossary)',
        'error': 'Translation error',
    }[desc]
    marker = '→ removable' if desc in ('exact', 'normalized') else '→ KEEP as correction'
    log(f'  {label:45s}: {count:>6} ({pct:5.1f}%)  {marker}')

removable = sum(1 for _, _, _, l, _ in results if l <= 1)
corrections = sum(1 for _, _, _, l, _ in results if l >= 2)
log(f'\n  REMOVABLE (Claude can handle):  {removable:>6} ({removable/len(results)*100:.1f}%)')
log(f'  CORRECTIONS (must keep):        {corrections:>6} ({corrections/len(results)*100:.1f}%)')

# ── Estimate API cost ──
# Rough: ~500 tokens per batch input + ~300 output = ~800 tokens/batch
est_input_tokens = total_batches * 800
est_output_tokens = total_batches * 400
log(f'\n  Estimated tokens: ~{est_input_tokens:,} input + ~{est_output_tokens:,} output')

# ── Write outputs ──
suffix = '_pilot' if PILOT_MODE else ''

full_path = OUT_DIR / f'comparison_full_claude{suffix}.csv'
with open(full_path, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f)
    w.writerow(['English', 'Glossary_Czech', 'Claude_Czech', 'Match_Level', 'Match_Desc'])
    for en, gcz, acz, level, desc in results:
        w.writerow([en, gcz, acz, level, desc])
log(f'\nFull comparison: {full_path}')

corr_path = OUT_DIR / f'corrections_claude{suffix}.csv'
with open(corr_path, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f)
    w.writerow(['English', 'Correct_Czech', 'Claude_Czech', 'Match_Desc'])
    for en, gcz, acz, level, desc in results:
        if level >= 2:
            w.writerow([en, gcz, acz, desc])
log(f'Corrections:     {corr_path}')

val_path = OUT_DIR / f'validated_claude{suffix}.csv'
with open(val_path, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f)
    w.writerow(['English', 'Czech', 'Claude_Czech', 'Match_Desc'])
    for en, gcz, acz, level, desc in results:
        if 0 <= level <= 1:
            w.writerow([en, gcz, acz, desc])
log(f'Validated:       {val_path}')

log(f'\nDone! Errors: {errors}')
_logf.close()
