import asyncio
import mido
import sys
import os
import json
from pydantic import BaseModel, Field
from typing import Optional, List

from mcp.server.fastmcp import FastMCP
from gp200mcp_sysex import SysExCodec

# define a more strict input for our chain setup method.
class KnobParameter(BaseModel):
    index: int = Field(..., description="The parameter index ID of the knob (starting from 0).")
    value: float = Field(..., description="The target float or integer setting value for this knob.")

class PedalConfiguration(BaseModel):
    Id: int = Field(..., description="The unique hardware numeric ID matching the pedal model name.")
    knobs: List[KnobParameter] = Field(default=[], description="Array containing targeted knob index configurations.")

class ModuleConfiguration(BaseModel):
    Module: str = Field(..., description="The effect slot block identifier name. Mandatory options: PRE, WAH, DST, AMP, NR, CAB, EQ, MOD, DLY, RVB, VOL.")
    Status: str = Field(..., description="The toggle state for this block module position. Choices: 'On' or 'Off'.")
    Pedal: Optional[PedalConfiguration] = Field(default=None, description="The inner hardware model configuration details. Set to null if the module is switched Off.")

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
DEFAULT_CHAIN_ORDER = ["PRE", "WAH", "DST", "AMP", "NR", "CAB", "EQ", "MOD", "DLY", "RVB", "VOL"]


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
async def switch_preset_slot(slot_number: int) -> str:
    """Change to a different stored preset on the GP-200 (0-255)."""
    if not midi_out: 
        return "Harware connection failed"
    
    sysex = SysExCodec.build_preset_change(slot_number)
    midi_out.send(mido.Message('sysex', data=sysex[1:-1]))
    return f"Switched to preset {slot_number}."

@mcp.tool()
def list_supported_pedal_by_category(categories: list[str]) -> dict:
    """
    Requests the supported guitar pedals, amplifiers and effects for MULTIPLE categories in one single call.
    Provide a list of categories to scan.

    AVAILABLE CATEGORIES TO CHOOSE FROM:
    - PRE (Pre-effects / Compressors)
    - WAH (Wah pedals)
    - DST (Overdrive / Distortion / Boost stompboxes)
    - AMP (Amplifier models / Preamps)
    - NR (Noise Reduction / Noise Gates)
    - CAB (Cabinet simulations / IRs)
    - EQ (Equalizers)
    - MOD (Modulation: Chorus, Flanger, Phaser, Tremolo)
    - DLY (Delays / Echoes)
    - RVB (Reverbs / Ambient spaces)
    - VOL (Global Volume pedal block)
    """
    output_result = {}
    if isinstance(categories, str):
        categories = [categories]
        
    for cat in categories:
        clean_cat = str(cat).upper().strip()
        
        # Find category
        target_category = None
        for item in PEDALS_DATABASE:
            current_name = item.get("Name")
            if current_name and str(current_name).upper().strip() == clean_cat:
                target_category = item
                break
                
        if not target_category:
            output_result[clean_cat] = []
            continue
            
        # Find effect/pedal
        effects_list = target_category.get("Effects") or []
        
        cat_pedals = []
        for pedal in effects_list:
            p_id = pedal.get("Id")
            p_name = pedal.get("Name")
            if p_id is not None and p_name:
                cat_pedals.append({"id": int(p_id), "name": str(p_name)})
                
        output_result[clean_cat] = cat_pedals
        
    return output_result  

@mcp.tool()
def show_pedal_details_by_pedal_ids(pedal_ids: list[int]) -> dict:
    """
    Requests complete configuration details for MULTIPLE pedals or amp models at once.
    Provide an array of unique pedal ID integers.
    
    This returns the full map of knobs (parameters), including their index IDs, 
    display names, minimum/maximum boundaries, increments, or explicit text 'options'.
    
    Use this tool before executing 'turn_knob' to discover which 'param_index' 
    controls which feature (e.g., Gain, Bass, Volume, Low Cut) and to verify safe values.
    """
    output_result = {}
    
    if isinstance(pedal_ids, int):
        pedal_ids = [pedal_ids]
        
    for p_id in pedal_ids:
        try:
            target_id = int(p_id)
        except (ValueError, TypeError):
            output_result[str(p_id)] = {"error": "Invalid pedal ID format."}
            continue
            
        found = False
        for category_item in PEDALS_DATABASE:
            effects_list = category_item.get("Effects") or []
            for pedal in effects_list:
                current_id = pedal.get("Id")
                if current_id is not None and int(current_id) == target_id:
                    raw_knobs = pedal.get("Knobs") or []
                    clean_knobs = []
                    
                    for k in raw_knobs:
                        # Extract explicit options if they exist
                        raw_options = k.get("Options") or []
                        clean_options = None
                        if raw_options:
                            clean_options = []
                            for opt in raw_options:
                                clean_options.append({
                                    "value": opt.get("Value", 0),
                                    "name": opt.get("Name", "Unknown")
                                })
                        
                        clean_knobs.append({
                            "id": k.get("Id", 0),
                            "name": k.get("Name", "Unknown"),
                            "min": k.get("Min"),
                            "max": k.get("Max"),
                            "step": k.get("Step"),
                            "options": clean_options
                        })
                        
                    output_result[str(target_id)] = {
                        "category": category_item.get("Name", "Unknown"),
                        "id": target_id,
                        "name": pedal.get("Name", "Unknown"),
                        "knobs": clean_knobs
                    }
                    found = True
                    break
            if found:
                break
                
        if not found:
            output_result[str(target_id)] = {"error": f"Pedal ID {target_id} not found."}
            
    return output_result





@mcp.tool()
def set_signal_chain(chain_configuration: list[ModuleConfiguration]) -> str:
    """
    Configures the entire guitar rig layout using a strictly validated input array. 
    It reorders the hardware chain matching the item sequence, overrides model slots, 
    switches modules ON/OFF, and applies knob configurations.
    
    Any blocks omitted from the array are safely appended to the chain tail 
    using manufacturer presets and are hard-toggled to 'Off'.
    """
    if not midi_out:
        return "Error: No active hardware connection."
    
    # turn off modules (everything, so it's quiet)
    set_all_modules_off()

    # change the order
    input_order = [item.Module.upper().strip() for item in chain_configuration]
    set_module_order(input_order)

    # set the correct pedal per module
    for item in chain_configuration:
        if item.Pedal is not None:
            set_pedal_model(item.Module.upper().strip(), item.Pedal.Id)

    # turn the knobs
    for item in chain_configuration:
        module_name = item.Module.upper().strip()
        pedal_data = item.Pedal
        
        if pedal_data is not None and pedal_data.knobs:
            for knob in pedal_data.knobs:
                turn_module_knob(module_name, knob.index, knob.value)

    # turn the modules on (only the ones listed in the input as ON)
    turned_on_pedals = [
        item.Module 
        for item in chain_configuration 
        if item.Status.upper().strip() == "ON"
    ]

    for module in turned_on_pedals:
        set_module_on_off(module, True)

    return ""

def turn_module_knob(module_name: str, knob_index: int, knob_value: float) -> None:
    clean_mod = str(module_name).upper().strip()
    if clean_mod in BLOCK_MAPPING:
        module_index = BLOCK_MAPPING[clean_mod]
        sysex = SysExCodec.build_param_change(module_index, int(knob_index), 0, float(knob_value))
        midi_out.send(mido.Message('sysex', data=list(sysex[1:-1])))
    

def set_all_modules_off():
    for module_index in BLOCK_MAPPING.values():        
        sysex = SysExCodec.build_toggle_effect(module_index, False)
        midi_out.send(mido.Message('sysex', data=sysex[1:-1]))

def set_module_on_off(module: str, state: bool) -> None:
    clean_mod = str(module).upper().strip()
    if clean_mod in BLOCK_MAPPING:
        module_index = BLOCK_MAPPING[clean_mod]
        sysex = SysExCodec.build_toggle_effect(module_index, state)
        midi_out.send(mido.Message('sysex', data=list(sysex[1:-1])))

def set_pedal_model(module_name: str, pedal_id: int) -> None:
    if not midi_out:
        return
        
    clean_mod = str(module_name).upper().strip()
    
    if clean_mod in BLOCK_MAPPING:
        module_index = BLOCK_MAPPING[clean_mod]
        sysex = SysExCodec.build_effect_change(module_index, int(pedal_id))
        midi_out.send(mido.Message('sysex', data=list(sysex[1:-1])))


# set chain helpers
def set_module_order(ordered_names: list[str], send_pos: int = 4, return_pos: int = 5) -> None:
    """
    Applies the structural routing order matrix to the device.
    If the input list contains less than 11 modules, the remaining missing modules
    are automatically appended to the end of the chain based on the factory defaults.
    """
    # 1. Clean the input and filter out any duplicates or invalid modules
    clean_input = []
    for m in ordered_names:
        mod_upper = str(m).upper().strip()
        if mod_upper in DEFAULT_CHAIN_ORDER and mod_upper not in clean_input:
            clean_input.append(mod_upper)
    
    # 2. Append the missing modules to the end of the chain
    final_order = list(clean_input)
    for fallback_mod in DEFAULT_CHAIN_ORDER:
        if fallback_mod not in final_order:
            final_order.append(fallback_mod)
            
    # 3. Translate to hardware indices and ship the 78-byte payload
    order_indices = [BLOCK_MAPPING[m] for m in final_order]
    sysex = SysExCodec.build_reorder_effects(order_indices, send_pos, return_pos)
    midi_out.send(mido.Message('sysex', data=list(sysex[1:-1])))


if __name__ == "__main__":
    mcp.run(transport="stdio")