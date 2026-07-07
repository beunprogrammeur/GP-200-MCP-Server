# GP-200-MCP-Server
An MCP server that allows your Valeton GP-200 (LT/JR) pedal to be controlled by an LLM

This work is entirely based on the works of [Phash's gp200editor](https://github.com/phash/gp200editor), amazing work! Thank you for doing all this!

Changes that were made on this code:
* converted the `SysExCodec.ts` file to python
* added an MCP server file that makes use of that converted code.


how to use:
run `Install.ps1` to create a virtual env for installing the required packages.

Then link up the mcp server to your LLM.

## How to link it up to your LLM
I've used a locally hosted LLM (Qwen 3.5 8B, others will probably work fine).

Software I used:
* vscode
* Roo Code extension.

In `Roo Code`, click on the `cog` icon -> `MCP Servers`
Check `Enable MCP Servers` and click `Edit Global MCP` (or  Project, up to you).

Then my MCP json config (tab opens):

```json
{
  "mcpServers": {
    "valeton-gp200-live": {
      "command": "cmd.exe",
      "args": [
        "/c",
        "path/to/repo/.venv/Scripts/activate.bat && python path/to/repo/gp200mcp.py"
      ]
    }
  }
}
```

if it works, your MCP server should show up in the list as `valeton-gp200-live`


# How to use

Once linked up, make sure your GP200 is turned on and connected over USB.

then you can just ask questions like `can you make me sound like Prince on Purple Rain` and it should try to set it up for you. Enjoy!

# Example

I've asked Qwen 3.5 9B (running local, I suspect you can run a smaller model for this as well) to:
`Can you make me sound like mark knopfler?`

It was then interested in the following categories:
```json
{
  "categories": [
    "PRE",
    "WAH",
    "DST",
    "AMP",
    "NR",
    "CAB",
    "EQ",
    "MOD",
    "DLY",
    "RVB",
    "VOL"
  ]
}
```

To then request the details on the following pedals:
```json
{
  "pedal_names": [
    "COMP",
    "Blues OD",
    "UK 45",
    "UK G12",
    "Analog",
    "Hall"
  ]
}
```

Giving us a response:
```
Now I have all the details needed to configure the chain. Let me set up a Mark Knopfler-inspired signal chain:

**Mark Knopfler Sound Profile:**
- Clean to slightly broken-up British amp tone
- Light compression for even fingerpicking dynamics
- Subtle overdrive for edge-of-breakup warmth
- Short, subtle delay for ambience
- Natural hall reverb for depth
- British 4x12 cabinet with Celestion speakers

**Chain Configuration:**
1. **COMP** (PRE): Light compression - Sustain ~40, Volume ~50
2. **Blues OD** (DST): Warm overdrive - Gain ~30, Tone ~60, Volume ~70
3. **UK 45** (AMP): British clean/edge - Gain ~20, Presence ~60, Volume ~80, Bass ~50, Middle ~50, Treble ~60
4. **UK G12** (CAB): British cabinet - Volume ~70, Low Cut ~100, High Cut ~8000
5. **Analog** (DLY): Short delay - Mix ~25, Time ~300, Feedback ~30, Sync OFF, Trail OFF
6. **Hall** (RVB): Natural reverb - Mix ~30, Pre Delay ~40, Decay ~60, Trail OFF

```


And ultimately setting up the chain in the GP-200 with the following settings:
```json
{
  "chain_configuration": [
    {
      "Module": "PRE",
      "Status": "On",
      "Pedal": {
        "Id": 1,
        "knobs": [
          {
            "index": 0,
            "value": 40
          },
          {
            "index": 1,
            "value": 50
          }
        ]
      }
    },
    {
      "Module": "DST",
      "Status": "On",
      "Pedal": {
        "Id": 3,
        "knobs": [
          {
            "index": 0,
            "value": 30
          },
          {
            "index": 1,
            "value": 60
          },
          {
            "index": 2,
            "value": 70
          }
        ]
      }
    },
    {
      "Module": "AMP",
      "Status": "On",
      "Pedal": {
        "Id": 14,
        "knobs": [
          {
            "index": 0,
            "value": 20
          },
          {
            "index": 1,
            "value": 60
          },
          {
            "index": 2,
            "value": 80
          },
          {
            "index": 3,
            "value": 50
          },
          {
            "index": 4,
            "value": 50
          },
          {
            "index": 5,
            "value": 60
          }
        ]
      }
    },
    {
      "Module": "CAB",
      "Status": "On",
      "Pedal": {
        "Id": 13,
        "knobs": [
          {
            "index": 1,
            "value": 70
          },
          {
            "index": 5,
            "value": 100
          },
          {
            "index": 6,
            "value": 8000
          }
        ]
      }
    },
    {
      "Module": "DLY",
      "Status": "On",
      "Pedal": {
        "Id": 1,
        "knobs": [
          {
            "index": 0,
            "value": 25
          },
          {
            "index": 1,
            "value": 300
          },
          {
            "index": 2,
            "value": 30
          },
          {
            "index": 3,
            "value": 0
          },
          {
            "index": 4,
            "value": 0
          }
        ]
      }
    },
    {
      "Module": "RVB",
      "Status": "On",
      "Pedal": {
        "Id": 0,
        "knobs": [
          {
            "index": 0,
            "value": 30
          },
          {
            "index": 1,
            "value": 40
          },
          {
            "index": 2,
            "value": 60
          },
          {
            "index": 3,
            "value": 0
          }
        ]
      }
    }
  ]
}
```

Whether this truy is what Mark Knopfler sounds like is of course up for debate, but if you keep asking to tune it in a certain direction, it should come closer and closer.