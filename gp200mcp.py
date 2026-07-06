import asyncio
import mido
import sys
import os
import json

from mcp.server.fastmcp import FastMCP
from gp200mcp_sysex import SysExCodec

mcp = FastMCP("valeton-gp200-stateless")
outputs = mido.get_output_names()
inputs = mido.get_input_names()

# Search for GP-200, GP-200LT or GP200JR
valeton_out = next((p for p in outputs if "GP" in p.upper() and "200" in p.upper()), None)
valeton_in = next((p for p in inputs if "GP" in p.upper() and "200" in p.upper()), None)


midi_out = None
midi_in = None
incoming_chunks = []

PEDALS_DATABASE = []
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(SCRIPT_DIR, "effects.json")

if os.path.exists(DB_FILE):
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            PEDALS_DATABASE = json.load(f)
        print(f"Connected to local catalog file: {DB_FILE}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Failed to parse catalog JSON: {str(e)}", file=sys.stderr)
else:
    print(f"Warning: {DB_FILE} not found!", file=sys.stderr)

def midi_callback(msg):
    global incoming_chunks
    if msg.type == 'sysex':
        full_bytes = bytes([0xF0] + list(msg.data) + [0xF7])
        incoming_chunks.append(full_bytes)

if valeton_out:
    midi_out = mido.open_output(valeton_out)
    print(f"Connected to USB MIDI Out: {valeton_out}", file=sys.stderr)
else:
    print("Warning: Valeton GP-200 MIDI Out not found.", file=sys.stderr)

if valeton_in:
    midi_in = mido.open_input(valeton_in, callback=midi_callback, ignore_types=[None])
    print(f"Connected to USB MIDI In: {valeton_in}", file=sys.stderr)
else:
    print("Warning: Valeton GP-200 MIDI In not found.", file=sys.stderr)

if midi_out:
    midi_out.send(mido.Message('sysex', data=SysExCodec.build_enter_editor_mode()[1:-1]))

async def wait_for_chunks(expected_count: int, timeout: float = 1.0) -> list[bytes]:
    global incoming_chunks
    start_time = asyncio.get_event_loop().time()
    
    try:
        while len(incoming_chunks) < expected_count:
            if asyncio.get_event_loop().time() - start_time > timeout:
                break
            await asyncio.sleep(0.01)
    except Exception as e:
        print(f"DEBUG: Error in chunk queue: {str(e)}", file=sys.stderr)
        
    chunks = list(incoming_chunks)
    incoming_chunks = []  # Clear buffer
    return chunks

BLOCK_MAPPING = {
    "PRE": 0, "WAH": 1, "DST": 2, "AMP": 3, "NR": 4, 
    "CAB": 5, "EQ": 6, "MOD": 7, "DLY": 8, "RVB": 9, "VOL": 10
}

@mcp.tool()
async def toggle_pedal(module_name: str, enabled: bool) -> str:
    """ module_name: 'PRE', 'DST', 'AMP', 'DLY', 'RVB' etc."""
    name_up = module_name.upper()
    if name_up not in BLOCK_MAPPING: 
        return f"Error, Choose from: {list(BLOCK_MAPPING.keys())}"
    if not midi_out: 
        return "Harware connection failed"
    
    sysex = SysExCodec.build_toggle_effect(BLOCK_MAPPING[name_up], enabled)
    midi_out.send(mido.Message('sysex', data=sysex[1:-1]))
    return f"Sent: {name_up} set to {'ON' if enabled else 'OFF'}."

@mcp.tool()
async def turn_knob(module_name: str, param_index: int, effect_id: int, value: float) -> str:
    """turns a knob of a module/pedal. module_name: DST, NR, AMP etc."""
    name_up = module_name.upper()
    if name_up not in BLOCK_MAPPING: 
        return "Unknown module."
    if not midi_out: 
        return "Harware connection failed"
    
    sysex = SysExCodec.build_param_change(BLOCK_MAPPING[name_up], param_index, effect_id, value)
    midi_out.send(mido.Message('sysex', data=sysex[1:-1]))
    return f"Parameter {param_index} changed from {name_up} to {value}."

@mcp.tool()
async def change_chain_order(ordered_modules: list[str], send_pos: int = 4, return_pos: int = 4) -> str:
    """Change the order of the signal chain. ALL 11 MODULES MUST BE LISTED, but you choose the order."""
    if not midi_out: 
        return "Harware connection failed"
    try:
        order_indices = [BLOCK_MAPPING[m.upper()] for m in ordered_modules]
    except KeyError:
        return f"Module name unknown: {list(BLOCK_MAPPING.keys())}"
        
    sysex = SysExCodec.build_reorder_effects(order_indices, send_pos, return_pos)
    midi_out.send(mido.Message('sysex', data=sysex[1:-1]))
    return f"Changed signal chain to: {' -> '.join(ordered_modules)}"

@mcp.tool()
async def switch_preset_slot(slot_number: int) -> str:
    """Change to a different stored preset on the GP-200 (0-255)."""
    if not midi_out: 
        return "Harware connection failed"
    
    sysex = SysExCodec.build_preset_change(slot_number)
    midi_out.send(mido.Message('sysex', data=sysex[1:-1]))
    return f"Switched to preset {slot_number}."

@mcp.tool()
def list_supported_pedal_categories() -> list:
    """
    Requests the supported types of pedals. examples: NR -> noise reducer. DST -> distortion etc. etc.
    """
    return [item["Name"] for item in PEDALS_DATABASE]

@mcp.tool()
def list_supported_pedal_by_category(category: str) -> list:
    """
    Requests the supported pedals that are in the given category.
    Passing in "DST" will then show a list of distortion and other boost pedals.
    """
    
    clean_cat = category.upper().strip()
    target_category = next((item for item in PEDALS_DATABASE if item["Name"] == clean_cat), None)
    
    if not target_category:
        return []
        
    return [{"id": pedal["Id"], "name": pedal["Name"]} for pedal in target_category["Effects"]] 

@mcp.tool()
def show_pedal_details_by_pedal_id(pedal_id: int) -> dict | None:
    """
    Requests all the details of a given pedal. this includes the name, id, what knobs it possesses, what the limits of those knobs are. etc.
    """
    for category_item in PEDALS_DATABASE:
        pedal = next((p for p in category_item["Effects"] if p["Id"] == pedal_id), None)
        if pedal:
            return {
                "category": category_item["Name"],
                "id": pedal["Id"],
                "name": pedal["Name"],
                "knobs": pedal["Knobs"]
            }
            
    return None

if __name__ == "__main__":
    mcp.run(transport="stdio")
