# GP-200-MCP-Server
An MCP server that allows your Valeton GP-200 (LT/JR) pedal to be controlled by an LLM

This work is entirely based on the works of [Phash's gp200editor](https://github.com/phash/gp200editor), amazing work!

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

