# reaper-mcp-server
An MCP server that lets language models interact with the Reaper DAW


```
git clone https://github.com/yeeking/reaper-mcp-server.git
cd reaper-mcp-server
## maybe maybe a venv
pip install -r requirements.txt
python src/reaper_mcp_server.py
```

Then configure your lm-studio or whatever to use tools then off you go. E.g. for lm-studio, put this in your mcp.json:

```
{
  "mcpServers": {
    "reaper-mcp": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

## Reaper setup 

You need to allow python to talk to Reaper - in the settings:

<img width="722" height="485" alt="image" src="https://github.com/user-attachments/assets/da6763e7-93a9-43c3-9af3-68b54dc1bcd2" />

I had these settings: 

```
/opt/homebrew/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/lib/

libpython3.12.dylib
```

Then I had to run a little script in reascript to open the API - swap 'your_venv_dir' for the locatipon of your virtual environment where you installed the packages earlier. Actions -> edit Reascript

```
import sys
sys.path.append("<your_venv_dir>/lib/python3.12/site-packages")
import reapy
reapy.config.enable_dist_api()
```
Run it and restart Reaper. 


## Security

There is none so watch out. 


