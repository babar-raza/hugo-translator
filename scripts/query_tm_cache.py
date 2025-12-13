"""Query TM cache for NuGet-related Bulgarian translations."""
import sys
sys.path.insert(0, 'src')
from pathlib import Path
import lmdb
import json

search_text = 'NuGet'
db_path = Path('data/tm/l2_lmdb')

# Write to file to avoid encoding issues
output_file = Path('tm_query_results.txt')

env = lmdb.open(str(db_path), readonly=True, lock=False)
with env.begin() as txn:
    cursor = txn.cursor()
    count = 0
    found_entries = []

    for key, value in cursor:
        try:
            entry = json.loads(value.decode('utf-8'))
            source = entry.get('source_text', '')
            translation = entry.get('translation', '')
            tgt_lang = entry.get('tgt_lang', '')

            # Look for NuGet in source or translation, Bulgarian target
            if (search_text in source or search_text in translation) and tgt_lang == 'bg':
                found_entries.append({
                    'key': key.decode('utf-8'),
                    'source': source,
                    'translation': translation,
                    'tgt_lang': tgt_lang,
                    'site_id': entry.get('site_id', 'unknown')
                })
            count += 1
        except Exception as e:
            pass

    # Write results to file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"Total entries scanned: {count}\n")
        f.write(f"Found {len(found_entries)} Bulgarian entries containing '{search_text}':\n\n")

        for i, e in enumerate(found_entries[:10], 1):
            f.write("=" * 60 + "\n")
            f.write(f"Entry {i}:\n")
            f.write(f"Key: {e['key']}\n")
            f.write(f"Site: {e['site_id']}\n")
            f.write(f"Source:\n{e['source']}\n\n")
            f.write(f"Translation:\n{e['translation']}\n\n")

env.close()
print(f"Results written to {output_file}")
