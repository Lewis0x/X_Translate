import csv, re
from collections import defaultdict
from pathlib import Path

path = str(Path(__file__).resolve().parent.parent / 'processed' / 'TransDict_CSY.csv')

with open(path, 'r', encoding='utf-8-sig') as f:
    rows = list(csv.reader(f))[1:]  # skip header
print(f'Input: {len(rows)} rows')

# ── Category 1: Remove untranslated entries (EN == CZ) ──
# Internal commands, block parameters, UI control names that serve no translation purpose
cat1 = 0
after_cat1 = []
for en, cz in rows:
    e, c = en.strip(), cz.strip()
    if e == c and len(e) > 3:
        # Check if it looks like an internal identifier / command name
        # (ALL_CAPS, CamelCase identifiers, underscored names, etc.)
        if (re.match(r'^[A-Z][A-Z0-9_]+$', e) or          # ALL_CAPS commands
            re.match(r'^[A-Za-z]+_[A-Za-z_]+', e) or       # underscore_names
            re.match(r'^[A-Z][a-z]+[A-Z]', e) or           # CamelCase
            re.match(r'^Button_', e) or                      # Button_XXX
            re.match(r'^DWG\d', e) or                        # DWG1NameLabel etc
            re.match(r'^[A-Za-z]+\d+$', e)):                 # Control IDs
            cat1 += 1
            continue
    after_cat1.append((en.strip(), cz.strip()))
print(f'Cat 1 - Untranslated internal names removed: {cat1}')

# ── Category 2: Remove &amp; HTML-encoded duplicates ──
# These duplicate the &-prefixed entries; keep the & version
cat2 = 0
after_cat2 = []
# Build set of plain-& entries for lookup
amp_entries = set()
for en, cz in after_cat1:
    if en.startswith('&') and not en.startswith('&amp;'):
        amp_entries.add(en)

for en, cz in after_cat1:
    if en.startswith('&amp;'):
        # Check if a corresponding &-prefixed version exists
        plain_en = en.replace('&amp;', '&', 1)
        # Also try without \tCtrl+X suffix for matching
        plain_base = re.sub(r'\t.*$', '', plain_en)
        has_match = any(
            e == plain_en or e == plain_base or e.startswith(plain_base)
            for e in amp_entries
        )
        if has_match:
            cat2 += 1
            continue
        # Even without exact match, &amp; entries are HTML artifacts - remove them
        # since the plain text is the correct form for CSV
        cat2 += 1
        continue
    after_cat2.append((en, cz))
print(f'Cat 2 - &amp; HTML duplicates removed: {cat2}')

# ── Category 3: Remove tail resource filenames, GUIDs, debug strings ──
cat3 = 0
after_cat3 = []
for en, cz in after_cat2:
    e = en.strip()
    # .h/.cpp/.rc resource filenames
    if re.match(r'^[A-Za-z0-9_]+\.(h|cpp|rc|dll|exe|arx|zrx|tx)$', e, re.IGNORECASE):
        cat3 += 1; continue
    # GUIDs like {D82704B7-...}
    if re.match(r'^\{[0-9A-Fa-f-]{36}\}$', e):
        cat3 += 1; continue
    # Internal debug strings with IID_
    if 'IID_' in e and ('QueryInterface' in e or 'Failed' in e):
        cat3 += 1; continue
    # Zcad_proxy type entries where EN==CZ
    if re.match(r'^Zcad_', e) and e == cz.strip():
        cat3 += 1; continue
    after_cat3.append((en, cz))
print(f'Cat 3 - Resource files/GUIDs/debug strings removed: {cat3}')

# ── Summary ──
total_removed = cat1 + cat2 + cat3
print(f'Total removed this round: {total_removed}')
print(f'Remaining: {len(after_cat3)} rows')

# ── Sort and write ──
after_cat3.sort(key=lambda x: x[0].lower())
with open(path, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f)
    w.writerow(['English', 'Czech'])
    for en, cz in after_cat3:
        w.writerow([en, cz])
print(f'Written to {path}')
