#!/usr/bin/env python3

import json
import os

from llmware.library import Library


lib = Library().create_new_library("kg_demo_vn")
nlp_folder = lib.nlp_path

parsed_blocks = []
for file_name in os.listdir(nlp_folder):
    if not (file_name.endswith(".json") or file_name.endswith(".jsonl")):
        continue

    file_path = os.path.join(nlp_folder, file_name)
    with open(file_path, "r", encoding="utf-8") as file_handle:
        for line in file_handle:
            if line.strip():
                parsed_blocks.append(json.loads(line))

print(f"Total blocks: {len(parsed_blocks)}")
if parsed_blocks:
    for index in range(min(5, len(parsed_blocks))):
        text = parsed_blocks[index].get("text_search", parsed_blocks[index].get("text", ""))
        print(f"Block {index}: {text[:200]}")
