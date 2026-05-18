# Scrapling MCP Setup

How to install and configure Scrapling MCP for OpenCode.

## Installation

### Docker (recommended — no system deps)

```bash
docker pull pyd4vinci/scrapling
```

### macOS (Homebrew)

```bash
brew install scrapling
```

### pip (any platform)

```bash
pip install "scrapling[ai]"
scrapling install
```

## OpenCode MCP Configuration

Add the following block to `~/.config/opencode/opencode.json` under the `"mcp"` key:

### Docker (recommended)

```json
{
  "mcp": {
    "scrapling": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "pyd4vinci/scrapling", "mcp"],
      "type": "local"
    }
  }
}
```

### Native (brew/pip)

```json
{
  "mcp": {
    "scrapling": {
      "command": ["/path/to/scrapling", "mcp"],
      "type": "local"
    }
  }
}
```

Run `which scrapling` to find the executable path.

## Available Tools

Once configured, the following MCP tools become available:

| Tool | Use |
|---|---|
| `scrapling_get` | Single-page HTTP GET with stealthy headers |
| `scrapling_bulk_get` | Parallel multi-page GET (use for pagination) |
| `scrapling_fetch` | Chromium-based dynamic content fetch |
| `scrapling_bulk_fetch` | Parallel multi-page browser fetch |
| `scrapling_stealthy_fetch` | Anti-bot bypass (Cloudflare, Turnstile) |
| `scrapling_screenshot` | Capture page screenshots (returns image the model can see) |
| `scrapling_open_session` | Create persistent browser session |
| `scrapling_close_session` | Close a browser session |
| `scrapling_list_sessions` | List active browser sessions |

## Key Parameters

For `scrapling_get` and `scrapling_bulk_get`:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` / `urls` | str / list[str] | required | Target URL(s) |
| `stealthy_headers` | bool | `true` | Use real browser headers |
| `timeout` | int | `30` | Request timeout in seconds |
| `extraction_type` | str | `"markdown"` | `"html"`, `"markdown"`, or `"text"` |
| `css_selector` | str | `null` | CSS selector to extract specific elements |
| `main_content_only` | bool | `true` | Extract only `<body>` content |

## Verification

After configuring, reload OpenCode. Test with:
```
scrapling_get(url="https://httpbin.org/get", stealthy_headers=true)
```
Expected: `{ "status": 200, ... }`

## Troubleshooting

| Error | Fix |
|---|---|
| MCP server "scrapling" not found | Reload OpenCode session, check config path |
| 401 Unauthorized | The portal may require authentication |
| 403 Forbidden | Use `stealthy_fetch` instead of `get` |
| Timeout | Increase timeout to 60+ seconds for slow servers |
| CSS selector returns empty | Check `main_content_only: false`, try broader selector |
