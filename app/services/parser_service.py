import json
import os

from bs4 import BeautifulSoup


def parse_and_mask(raw_content: str, file_format: str, temps_dir: str):
    """
    Парсит входной текст и возвращает:
    (ai_friendly_dict, key_bridge, is_nested_json)
    """
    original_map = {}
    is_nested_json = False

    if file_format == "json":
        raw_data = json.loads(raw_content)
        
        def flatten_json(y):
            out = {}
            def flatten(x, name=""):
                if type(x) is dict:
                    for a in x: flatten(x[a], name + a + ".")
                elif type(x) is list:
                    for i, a in enumerate(x): flatten(a, name + str(i) + ".")
                else: out[name[:-1]] = str(x)
            flatten(y)
            return out

        if any(isinstance(v, dict) for v in raw_data.values()):
            original_map = flatten_json(raw_data)
            is_nested_json = True
        else:
            original_map = {str(k): str(v) for k, v in raw_data.items() if v}

    elif file_format == "xml":
        soup = BeautifulSoup(raw_content, "lxml-xml")
        for i, element in enumerate(soup.find_all(string=True)):
            text = element.strip()
            if text and not text.startswith("<?xml"):
                original_map[f"xml_tag_{i}"] = text
                element.replace_with(f"__TOKEN_xml_tag_{i}__")
        
        with open(os.path.join(temps_dir, ".xml_template_cache"), "w", encoding="utf-8") as f:
            f.write(str(soup))
            
    else: # text
        lines = raw_content.split("\n")
        for i, line in enumerate(lines):
            original_map[f"text_line_{i}"] = line

    ai_friendly_dict = {}
    key_bridge = {}
    
    for idx, (orig_key, orig_text) in enumerate(original_map.items()):
        ai_key = f"text_{idx}"
        ai_friendly_dict[ai_key] = orig_text
        key_bridge[ai_key] = orig_key

    return ai_friendly_dict, key_bridge, is_nested_json