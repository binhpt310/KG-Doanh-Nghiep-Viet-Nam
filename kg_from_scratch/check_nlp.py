import os
import json
from llmware.library import Library

lib = Library().create_new_library("kg_demo_vn")
nlp_folder = lib.nlp_path

parsed_blocks = []
for fname in os.listdir(nlp_folder):
    if fname.endswith(".json") or fname.endswith(".jsonl"):
        filepath = os.path.join(nlp_folder, fname)
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    parsed_blocks.append(json.loads(line))

print(f"Total blocks: {len(parsed_blocks)}")
if parsed_blocks:
    for i in range(min(5, len(parsed_blocks))):
        print(f"Block {i}: {parsed_blocks[i].get('text_search', parsed_blocks[i].get('text', ''))[:200]}")
