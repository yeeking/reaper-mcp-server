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




