import math
import re
import struct

class SysExCodec:
    @staticmethod
    def encode_display_value(value: float) -> bytes:
        u16 = 0
        if value > 0:
            u16 = round(16367 + 16 * math.log2(value))
            if u16 < 0:
                u16 = 0
            if u16 > 0xFFFF:
                u16 = 0xFFFF
        
        return bytes([u16 & 0xFF, (u16 >> 8) & 0xFF])

    @staticmethod
    def nibble_decode(data: bytes | bytearray) -> bytearray:
        out = bytearray(len(data) // 2)
        for i in range(len(out)):
            out[i] = ((data[2 * i] & 0x0F) << 4) | (data[2 * i + 1] & 0x0F)
        return out

    @staticmethod
    def nibble_encode(data: bytes | bytearray) -> bytearray:
        out = bytearray(len(data) * 2)
        for i in range(len(data)):
            out[2 * i]     = (data[i] >> 4) & 0x0F
            out[2 * i + 1] = data[i] & 0x0F
        return out

    @staticmethod
    def slot_to_label(slot: int) -> str:
        bank = (slot // 4) + 1
        letter = 'ABCD'[slot % 4]
        return f"{bank}{letter}"

    @staticmethod
    def label_to_slot(label: str) -> int:
        match = re.match(r"^(\d+)([ABCD])$", label.upper())
        if not match:
            raise ValueError(f"Invalid slot label: {label}")
        
        bank = int(match.group(1))
        letter_idx = 'ABCD'.index(match.group(2))
        return (bank - 1) * 4 + letter_idx

    @staticmethod
    def build_read_request(slot: int) -> bytes:
        sh = (slot >> 4) & 0x0F
        sl = slot & 0x0F
        
        return bytes([
            0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32,  # [0-7]   Header
            0x11, 0x10,                                      # [8-9]   CMD, sub
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  # [10-17] Padding
            0x04, 0x00, 0x00, 0x00,                          # [18-21] Constant
            0x01, 0x00,                                      # [22-23] Constant
            0x00,                                            # [24]    Padding
            sh, sl,                                          # [25-26] Slot nibble (high, low)
            0x00, 0x00, 0x00,                                # [27-29] Padding
            0x01, 0x00,                                      # [30-31] Constant
            0x00, 0x00,                                      # [32-33] Padding
            0x04, 0x00, 0x00,                                # [34-36] Constant
            sh, sl,                                          # [37-38] Slot nibble
            0x00, 0x00,                                      # [39-40] Padding
            sh, sl,                                          # [41-42] Slot nibble
            0x00, 0x00,                                      # [43-44] Padding
            0xF7,                                            # [45]    End
        ])

    @classmethod
    def parse_preset_name(cls, sysex_msg: bytes | bytearray) -> str:
        nibble_data = sysex_msg[13:-1]
        decoded = cls.nibble_decode(nibble_data)
        
        name_chars = []
        for i in range(16):
            b = decoded[28 + i]
            if b == 0:
                break
            name_chars.append(chr(b))
            
        return "".join(name_chars)

    @classmethod
    def assemble_chunks(cls, chunks: list[bytes | bytearray]) -> bytearray:
        sorted_chunks = sorted(
            chunks, 
            key=lambda msg: msg[11] | (msg[12] << 8)
        )
        
        nibble_parts = [msg[13:-1] for msg in sorted_chunks]
        
        all_nibbles = bytearray()
        for part in nibble_parts:
            all_nibbles.extend(part)
            
        return cls.nibble_decode(all_nibbles)

    @classmethod
    def parse_preset_from_decoded(cls, decoded: bytearray, fallback_name: str = None) -> dict:
        """
        Parses the complete decoded byte-array to a readable python dict. format.
        maps patchname, author, FX loop and all 11 effect slots with their live knob values.
        """
        patch_name = ""
        if len(decoded) > 43:
            name_bytes = decoded[28:44]
            if 0 in name_bytes:
                name_bytes = name_bytes[:name_bytes.index(0)]
            patch_name = name_bytes.decode('ascii', errors='ignore').strip()
            
        if not patch_name and fallback_name:
            patch_name = fallback_name

        author = ""
        if len(decoded) > 59:
            author_bytes = decoded[44:60]
            if 0 in author_bytes:
                author_bytes = author_bytes[:author_bytes.index(0)]
            author = author_bytes.decode('ascii', errors='ignore').strip()

        raw_send = decoded[106] if len(decoded) > 106 else 4
        raw_return = decoded[107] if len(decoded) > 107 else 4
        fx_loop_send = raw_send if (1 <= raw_send <= 10) else 4
        fx_loop_return = raw_return if (1 <= raw_return <= 10) else 4

        effects = []
        for b in range(11):
            base = 120 + (b * 72)
            if base + 72 > len(decoded):
                effects.append({
                    "slotIndex": b,
                    "enabled": False,
                    "effectId": 0,
                    "params": [0.0] * 15
                })
                continue
                
            slot_index = decoded[base + 4]
            enabled = decoded[base + 5] == 1
            
            effect_id = struct.unpack_from("<I", decoded, base + 8)[0]
            
            params = []
            for p in range(15):
                param_offset = base + 12 + (p * 4)
                param_val = struct.unpack_from("<f", decoded, param_offset)[0]
                params.append(param_val)

            effects.append({
                "slotIndex": slot_index,
                "enabled": enabled,
                "effectId": effect_id,
                "params": params
            })

        return {
            "version": "1",
            "patchName": patch_name,
            "author": author if author else None,
            "fxLoopSend": fx_loop_send,
            "fxLoopReturn": fx_loop_return,
            "effects": effects,
            "checksum": 0
        }

    @classmethod
    def parse_read_chunks(cls, chunks: list[bytes | bytearray]) -> dict:
        decoded = cls.assemble_chunks(chunks)
        return cls.parse_preset_from_decoded(decoded)

    @classmethod
    def build_write_chunks(cls, preset: dict, slot: int) -> list[bytes]:
        """
        [HARDWARE UNRELIABLE for this mechanism]
        Writes 5 SysEx-chunks for a full preset-bytearray (876 bytes) to write to a specific memory slot.
        """
        SYSEX_HEADER = [0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32, 0x12, 0x20]
        PAYLOAD_SIZE = 876
        payload = bytearray(PAYLOAD_SIZE)

        header_bytes = [
            0x00, 0x00, 0x04, 0x00, 0x01, 0x00, 0x27, 0x00,
            0x01, 0x00, 0x04, 0x00, 0x27, 0x00, 0x27, 0x00,
            0x02, 0x00, 0x58, 0x00, 0x27, 0x00, 0x78, 0x00,
            0x32, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00
        ]
        payload[0:36] = header_bytes

        name_bytes = preset["patchName"].encode('ascii', errors='ignore')[:16]
        payload[36:36+len(name_bytes)] = name_bytes

        if preset.get("author"):
            author_bytes = preset["author"].encode('ascii', errors='ignore')[:16]
            payload[52:52+len(author_bytes)] = author_bytes


        payload[108:112] = [0x08, 0x00, 0x10, 0x00]
        payload[112] = 0x25  # Static write marker
        payload[113] = 0x00
        payload[114] = preset.get("fxLoopSend", 4)
        payload[115] = preset.get("fxLoopReturn", 4)
        
        for i in range(11):
            if i < len(preset["effects"]):
                payload[116 + i] = preset["effects"][i].get("slotIndex", i)
            else:
                payload[116 + i] = i

        def safe_param(v):
            if v is not None and math.isfinite(v):
                return float(v)
            return 0.0

        for b in range(8):
            base = 128 + b * 72
            if b >= len(preset["effects"]):
                continue
            eff = preset["effects"][b]
            payload[base:base+8] = [0x14, 0x00, 0x44, 0x00, eff["slotIndex"], 1 if eff["enabled"] else 0, 0x00, 0x0F]
            struct.pack_into("<I", payload, base + 8, eff["effectId"])
            for p in range(15):
                val = safe_param(eff["params"][p]) if p < len(eff["params"]) else 0.0
                struct.pack_into("<f", payload, base + 12 + p * 4, val)

        if len(preset["effects"]) > 8 and preset["effects"][8]:
            base = 704
            eff = preset["effects"][8]
            payload[base:base+8] = [0x14, 0x00, 0x44, 0x00, eff["slotIndex"], 1 if eff["enabled"] else 0, 0x00, 0x0F]
            struct.pack_into("<I", payload, base + 8, eff["effectId"])
            for p in range(15):
                val = safe_param(eff["params"][p]) if p < len(eff["params"]) else 0.0
                struct.pack_into("<f", payload, base + 12 + p * 4, val)

        if len(preset["effects"]) > 9 and preset["effects"][9]:
            base = 776
            eff = preset["effects"][9]
            payload[base:base+8] = [0x14, 0x00, 0x44, 0x00, eff["slotIndex"], 1 if eff["enabled"] else 0, 0x00, 0x0F]
            struct.pack_into("<I", payload, base + 8, eff["effectId"])
            for p in range(15):
                val = safe_param(eff["params"][p]) if p < len(eff["params"]) else 0.0
                struct.pack_into("<f", payload, base + 12 + p * 4, val)

        if len(preset["effects"]) > 10 and preset["effects"][10]:
            base = 848
            eff = preset["effects"][10]
            payload[base:base+8] = [0x14, 0x00, 0x44, 0x00, eff["slotIndex"], 1 if eff["enabled"] else 0, 0x00, 0x0F]
            struct.pack_into("<I", payload, base + 8, eff["effectId"])
            for p in range(4):  
                val = safe_param(eff["params"][p]) if p < len(eff["params"]) else 0.0
                struct.pack_into("<f", payload, base + 12 + p * 4, val)

        nibble = cls.nibble_encode(payload)
        CHUNK_SIZE = 366
        CHUNK_OFFSETS = [0, 311, 622, 1061, 1372]
        
        chunks = []
        num_chunks = math.ceil(len(nibble) / CHUNK_SIZE)
        
        for i in range(num_chunks):
            nibble_data = nibble[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
            off_lo = CHUNK_OFFSETS[i] & 0xFF
            off_hi = (CHUNK_OFFSETS[i] >> 8) & 0xFF

            chunk_bytes = bytearray()
            chunk_bytes.extend(SYSEX_HEADER)
            chunk_bytes.append(slot & 0xFF)
            chunk_bytes.append(off_lo)
            chunk_bytes.append(off_hi)
            chunk_bytes.extend(nibble_data)
            chunk_bytes.append(0xF7)
            chunks.append(bytes(chunk_bytes))
            
        return chunks

    @staticmethod
    def build_identity_query() -> bytes:
        return bytes([
            0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32,
            0x11, 0x04,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00,
            0xF7,
        ])

    @staticmethod
    def build_enter_editor_mode() -> bytes:
        return bytes([
            0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32,
            0x11, 0x12,
            0x00, 0x00, 0x00,
            0xF7,
        ])

    @staticmethod
    def build_state_dump_request() -> bytes:
        return bytes([
            0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32,
            0x11, 0x04,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00,
            0xF7,
        ])

    @staticmethod
    def build_version_check() -> bytes:
        return bytes([
            0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32,
            0x11, 0x0A,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x06, 0x00, 0x00,
            0x0D, 0x04, 0x0F, 0x07, 0x08, 0x0B, 0x00, 0x00, 0x0C, 0x0B, 0x04, 0x05,
            0xF7,
        ])

    @staticmethod
    def build_assignment_query(section: int, page: int, block: int) -> bytes:
        SEC0_HDR = [0x00, 0x00, 0x00, 0x00, 0x09, 0x01, 0x00, 0x01, 0x08]
        SEC1_HDR = [0x00, 0x00, 0x00, 0x01, 0x02, 0x01, 0x00, 0x01, 0x08]
        header = SEC1_HDR if section == 1 else SEC0_HDR
        
        REF_DATA = [
            0x01, 0x00, 0x00,
            0x0C, 0x0E, 0x07, 0x03, 0x0B, 0x02, 0x00, 0x00,
            0x07, 0x02, 0x04, 0x0F, 0x06, 0x05, 0x00, 0x09,
            0x00, 0x0C, 0x0F, 0x0E, 0x0D, 0x0A, 0x00, 0x0B,
            0x09, 0x08, 0x07, 0x05, 0x0E, 0x08, 0x00, 0x02,
            0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        ]
        
        msg = bytearray([0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32, 0x11, 0x1C])
        msg.extend(header)
        msg.extend([0x00, 0x00])
        msg.append(page & 0xFF)
        msg.append(block & 0x0F)
        msg.extend([0x00, 0x00, 0x00])
        msg.extend(REF_DATA)
        msg.append(0xF7)
        return bytes(msg)

    @staticmethod
    def parse_identity_response(msg: bytes | bytearray) -> dict:
        """Retrieves device type (byte 18)."""
        if len(msg) > 18:
            return {"deviceType": msg[18], "firmwareValues": []}
        return {"deviceType": 0, "firmwareValues": []}

    @staticmethod
    def parse_version_response(msg: bytes | bytearray) -> dict:
        """Response validation"""
        if len(msg) < 34:
            return {"accepted": False}
        if msg[0] != 0xF0:
            return {"accepted": False}
        if msg[8] != 0x12:  # Device > host marker
            return {"accepted": False}
        if msg[9] != 0x0A:  # Sub-command version check
            return {"accepted": False}
        return {"accepted": True}

    @classmethod
    def parse_assignment_response(cls, msg: bytes | bytearray, section: int, page: int) -> dict:
        """Parses the effect name from a response."""
        block = msg[22] if len(msg) > 22 else 0
        nibble_data = msg[27:-1]
        decoded = cls.nibble_decode(nibble_data)
        
        name_chars = []
        name_start = 0
        while name_start < len(decoded) and decoded[name_start] == 0:
            name_start += 1
            
        for i in range(name_start, len(decoded)):
            if decoded[i] == 0:
                break
            name_chars.append(chr(decoded[i]))
            
        return {
            "section": section,
            "page": page,
            "block": block,
            "name": "".join(name_chars),
            "rawData": bytes(decoded)
        }

    @classmethod
    def parse_state_dump(cls, chunks: list[bytes | bytearray]) -> dict:
        """Determines the active preset-slot (0-255) from a live state dump"""
        if not chunks:
            return {"slot": 0}
        decoded = cls.assemble_chunks(chunks)
        if len(decoded) >= 10:
            # Slot is opgeslagen als 16-bit Little Endian integer op byte 8 en 9
            slot = decoded[8] | (decoded[9] << 8)
            if 0 <= slot < 256:
                return {"slot": slot}
        return {"slot": 0}

    @staticmethod
    def build_toggle_effect(block_index: int, enabled: bool) -> bytes:
        """
        Blok indices: 
        0=PRE, 1=WAH, 2=BOOST, 3=AMP, 4=NR, 5=CAB, 6=EQ, 7=MOD, 8=DLY, 9=RVB, 10=VOL
        """
        return bytes([
            0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32,  # [0-7]   Header
            0x12, 0x10,                                      # [8-9]   CMD, sub
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  # [10-17] Padding
            0x04, 0x00, 0x00, 0x00,                          # [18-21] Constant
            0x00, 0x00, 0x00,                                # [22-24] Padding
            0x00, 0x00,                                      # [25-26] Zeros
            0x00, 0x00,                                      # [27-28] Padding
            0x01, 0x05,                                      # [29-30] Constant
            0x00, 0x00, 0x00,                                # [31-33] Padding
            0x04, 0x00, 0x00, 0x00,                          # [34-37] Constant
            block_index & 0x0F,                              # [38]    Phyisical blok index
            0x00,                                            # [39]    Padding
            0x01 if enabled else 0x00,                       # [40]    ON (0x01) or OFF (0x00)
            0x09, 0x0C,                                      # [41-42] Constant
            0x00, 0x02,                                      # [43-44] Constant
            0xF7,                                            # [45]    End
        ])

    @staticmethod
    def build_effect_change(block_index: int, effect_id: int) -> bytes:
        module_type = (effect_id >> 24) & 0xFF
        variant = effect_id & 0xFF
        
        msg = bytearray([
            0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32,  # Header
            0x12, 0x14,                                      # CMD=SET, sub=EFFECT_CHANGE
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x04, 0x00, 0x00, 0x00,                          # Constant
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x01, 0x06,                                      # Constant
            0x00, 0x00, 0x00,
            0x08,                                            # Constant
            0x00, 0x00, 0x00,
            block_index & 0x0F,                              # Block index (0-10)
            0x00, 0x00,
            0x07, 0x06, 0x00, 0x02,                          # Constant
            (variant >> 4) & 0x0F,                           # Variant high nibble
            variant & 0x0F,                                  # Variant low nibble
            0x00, 0x00, 0x00, 0x00, 0x00,
            module_type & 0xFF,                              # Module type
            0xF7                                             # End
        ])
        return bytes(msg)

    @classmethod
    def build_param_change(cls, block_index: int, param_index: int, effect_id: int, value: float) -> bytes:
        decoded = bytearray(24)
        decoded[2] = 0x04                            # Constant
        decoded[8] = 0x05                            # Message type: param change
        decoded[10] = 0x0C                           # Constant
        decoded[12] = block_index & 0xFF
        decoded[13] = param_index & 0xFF
        
        # Little endian
        disp = cls.encode_display_value(value)
        decoded[14] = disp[0]
        decoded[15] = disp[1]
        
        struct.pack_into("<I", decoded, 16, effect_id)
        struct.pack_into("<f", decoded, 20, float(value))
        
        # Nibble encode data and wrap in sysex envelope
        nibbles = cls.nibble_encode(decoded)
        msg = bytearray([0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32, 0x12, 0x18, 0x00, 0x00, 0x00])
        msg.extend(nibbles)
        msg.append(0xF7)
        return bytes(msg)

    @staticmethod
    def build_patch_setting(target: int, value: int) -> bytes:
        """
        changes global patch settings.
        target: 0x00=VOL, 0x01=Tempo, 0x06=PAN
        """
        msg = bytearray([
            0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32,
            0x12, 0x10,                                      # CMD, sub
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x04, 0x00, 0x00, 0x00,                          # Constant
            0x00, 0x00, 0x00,
            0x00, 0x00,
            0x00, 0x00,
            0x00, 0x06,                                      # Patch setting constant
            0x00, 0x00, 0x00,
            0x04, 0x00, 0x00, 0x00,                          # Constant
            target & 0x0F,                                   # Target (VOL/Tempo/PAN)
            0x00,
            0x00,
            (value >> 4) & 0x0F,                             # Value high nibble
            value & 0x0F,                                    # Value low nibble
            0x00, 0x00,                                      # Padding
            0xF7
        ])
        
        # PAN left of middle: values 128-255 require specific values
        if target == 0x06 and value > 127:
            msg[43] = 0x0F
            msg[44] = 0x0F
            
        # Tempo larger than 255 requires splitting the value in 4 nibbles
        if target == 0x01 and value > 255:
            msg[41] = (value >> 4) & 0x0F
            msg[42] = value & 0x0F
            msg[43] = (value >> 12) & 0x0F
            msg[44] = (value >> 8) & 0x0F
            
        return bytes(msg)

    @classmethod
    def build_reorder_effects(cls, order: list[int], send: int, ret: int) -> bytes:
        decoded = bytearray(32)
        decoded[2] = 0x04                             # Constant
        decoded[8] = 0x08                             # Msg type: reorder
        decoded[10] = 0x10                            # Constant
        decoded[14] = send & 0xFF                     # SEND positie (1..10)
        decoded[15] = ret & 0xFF                      # RETURN positie (1..10)
        
        for i in range(11):
            if i < len(order):
                decoded[16 + i] = order[i]
                
        decoded[27] = 0x44                            # Terminator marker for reorder
        
        nibbles = cls.nibble_encode(decoded)
        msg = bytearray([0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32, 0x12, 0x20, 0x00, 0x00, 0x00])
        msg.extend(nibbles)
        msg.append(0xF7)
        return bytes(msg)

    @classmethod
    def build_fx_loop_move(cls, order: list[int], send: int, ret: int, which: str) -> bytes:
        decoded = bytearray(32)
        decoded[2] = 0x04
        decoded[6] = 0x51
        decoded[8] = 0x08
        decoded[10] = 0x10
        decoded[12] = 0x51
        decoded[14] = send & 0xFF
        decoded[15] = ret & 0xFF
        
        for i in range(11):
            if i < len(order):
                decoded[16 + i] = order[i]
                
        decoded[27] = 0x08 if which.lower() == 'send' else 0xBA
        
        nibbles = cls.nibble_encode(decoded)
        msg = bytearray([0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32, 0x12, 0x20, 0x00, 0x00, 0x00])
        msg.extend(nibbles)
        msg.append(0xF7)
        return bytes(msg)

    @classmethod
    def build_save_commit(cls, preset_name: str, slot: int) -> bytes:
        decoded = bytearray(24)
        decoded[0] = 0x03
        decoded[1] = 0x20
        decoded[2] = 0x14
        decoded[4] = slot & 0xFF
        
        name_bytes = preset_name.encode('ascii', errors='ignore')[:16]
        decoded[8:8+len(name_bytes)] = name_bytes
        
        nibbles = cls.nibble_encode(decoded)
        msg = bytearray([0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32, 0x12, 0x18, 0x00, 0x00, 0x00])
        msg.extend(nibbles)
        msg.append(0xF7)
        return bytes(msg)

    @classmethod
    def build_author_name(cls, author: str) -> bytes:
        decoded = bytearray(32)
        decoded[2] = 0x04
        decoded[6] = 0x01
        decoded[8] = 0x09  # Message type: Author
        decoded[10] = 0x14
        decoded[12] = 0x01
        decoded[14] = 0x70
        decoded[15] = 0x0B
        
        author_bytes = author.encode('ascii', errors='ignore')[:16]
        decoded[16:16+len(author_bytes)] = author_bytes
        
        nibbles = cls.nibble_encode(decoded)
        msg = bytearray([0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32, 0x12, 0x20, 0x00, 0x00, 0x00])
        msg.extend(nibbles)
        msg.append(0xF7)
        return bytes(msg)

    @classmethod
    def build_style_name(cls, style_name: str) -> bytes:
        decoded = bytearray(24)
        decoded[0] = 0x03
        decoded[1] = 0x20
        decoded[2] = 0x14
        decoded[4] = 0x01
        decoded[6] = 0xA1
        
        style_bytes = style_name.encode('ascii', errors='ignore')[:16]
        decoded[8:8+len(style_bytes)] = style_bytes
        
        nibbles = cls.nibble_encode(decoded)
        msg = bytearray([0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32, 0x12, 0x18, 0x00, 0x00, 0x00])
        msg.extend(nibbles)
        msg.append(0xF7)
        return bytes(msg)

    @classmethod
    def build_note(cls, note: str) -> bytes:
        decoded = bytearray(56)
        decoded[2] = 0x04
        decoded[6] = 0x01
        decoded[8] = 0x0B  # Message type: Note
        decoded[10] = 0x2C
        decoded[12] = 0x01
        decoded[14] = 0xA1
        
        note_bytes = note.encode('ascii', errors='ignore')[:40]
        decoded[16:16+len(note_bytes)] = note_bytes
        
        nibbles = cls.nibble_encode(decoded)
        msg = bytearray([0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32, 0x12, 0x38, 0x00, 0x00, 0x00])
        msg.extend(nibbles)
        msg.append(0xF7)
        return bytes(msg)

    @classmethod
    def build_exp_navigation(cls, page: int, item: int = None, block_index: int = None, param_index: int = None) -> bytes:
        decoded = bytearray(24)
        decoded[2] = 0x04
        decoded[8] = 0x0C
        decoded[10] = 0x0C
        decoded[11] = page & 0xFF
        decoded[12] = (item if item is not None else 0) & 0x0F
        decoded[13] = (block_index if block_index is not None else 0) & 0x0F
        decoded[14] = (param_index if param_index is not None else 0) & 0x0F
        decoded[18] = 0xC8
        decoded[19] = 0x42
        
        nibbles = cls.nibble_encode(decoded)
        msg = bytearray([0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32, 0x12, 0x18, 0x00, 0x00, 0x00])
        msg.extend(nibbles)
        msg.append(0xF7)
        return bytes(msg)

    @classmethod
    def build_exp_assignment(cls, section: int, page: int, item: int, value: float) -> bytes:
        decoded = bytearray(6)
        decoded[0] = 0x40
        decoded[1] = 0x0C
        struct.pack_into("<f", decoded, 2, float(value))
        
        nibbles = cls.nibble_encode(decoded)
        msg = bytearray([
            0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32,
            0x12, 0x14,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x04, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x0E,
            0x00, 0x00, 0x00,
            0x08,
            0x00, 0x00, 0x00,
            section & 0x01,
            page & 0xFF,
            item & 0x0F
        ])
        msg.extend(nibbles)
        msg.append(0xF7)
        return bytes(msg)

    @staticmethod
    def build_preset_change(slot: int) -> bytes:
        sh = (slot >> 4) & 0x0F
        sl = slot & 0x0F
        return bytes([
            0xF0, 0x21, 0x25, 0x7E, 0x47, 0x50, 0x2D, 0x32,  # Header
            0x12, 0x08,                                      # CMD, sub
            0x00, 0x00, 0x00, 0x00,                          # Padding
            0x08, 0x01,                                      # Constant
            0x00, 0x00,                                      # Padding
            0x04, 0x00, 0x00, 0x00,                          # Constant
            0x00, 0x00, 0x00,                                # Padding
            sh,                                              # Slot high nibble
            sl,                                              # Slot low nibble
            0x00, 0x00,                                      # Extra padding byte
            0xF7                                             # End
        ])
