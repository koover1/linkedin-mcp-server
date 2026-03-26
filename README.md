# LinkedIn MCP Server (Fork)

> **This is a fork of [stickerdaniel/linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server).** It adds LinkedIn messaging capabilities and other modifications for personal use. For the canonical, maintained version, see the upstream repo.

## Why this fork?

The upstream LinkedIn MCP server provides read-only tools for scraping profiles, companies, and jobs. This fork adds:

- **`send_message` tool** -- Send LinkedIn messages directly through the MCP server. Supports both Premium messaging (inline compose overlay) and Recruiter InMail (new tab), with automatic path detection, dry-run mode, and debug screenshots.
- **Headed browser by default** -- Browser launches visibly for easier debugging and monitoring.
- **`mask_error_details=False`** -- Full error details exposed to MCP clients for better debugging during development.
- **Logging fix** -- `CompactFormatter` now uses consistent record references.
- **`open_browser.py`** -- Utility script to launch a headed browser with the stored LinkedIn profile for manual inspection.

## Upstream features (inherited)

All upstream tools are available:

| Tool | Description |
|------|-------------|
| `get_person_profile` | Get profile info with section selection (experience, education, interests, etc.) |
| `get_company_profile` | Extract company information with section selection (posts, jobs) |
| `get_company_posts` | Get recent posts from a company's LinkedIn feed |
| `search_jobs` | Search for jobs with keywords, location, and filters |
| `search_people` | Search for people by keywords and location |
| `get_job_details` | Get detailed information about a specific job posting |
| `close_session` | Close browser session and clean up resources |

## New in this fork

| Tool | Description |
|------|-------------|
| `send_message` | Send a LinkedIn message to a user by username. Detects Premium overlay vs Recruiter InMail automatically. Supports `dry_run`, custom `subject` lines, and captures debug screenshots at each step. |

### `send_message` usage

```
Send a message to oliverzhang42 on LinkedIn saying "Hi Oliver, great to connect!"
```

**Parameters:**

- `linkedin_username` (required) -- LinkedIn username (e.g., `"oliverzhang42"`)
- `message` (required) -- Plain text message body
- `subject` -- Subject line for Recruiter InMail (default: `"Opportunity at the Center for AI Safety"`)
- `dry_run` -- If `True`, navigates and types the message but does not click Send

## Setup

This fork uses the same setup as upstream. You need Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
# Clone this fork
git clone https://github.com/koover1/linkedin-mcp-server
cd linkedin-mcp-server

# Install dependencies
uv sync

# Install browser
uv run patchright install chromium

# Log in to LinkedIn (first time only)
uv run -m linkedin_mcp_server --login

# Start the server
uv run -m linkedin_mcp_server
```

### Claude Desktop configuration

```json
{
  "mcpServers": {
    "linkedin": {
      "command": "uv",
      "args": ["--directory", "/path/to/linkedin-mcp-server", "run", "-m", "linkedin_mcp_server"]
    }
  }
}
```

### Manual browser inspection

```bash
python open_browser.py
```

Opens a headed Chromium using your stored LinkedIn profile for manual testing.

## Divergence from upstream

This fork diverged from upstream at commit [`9c1ec5e`](https://github.com/stickerdaniel/linkedin-mcp-server/commit/9c1ec5e) (v4.4.1). It is not kept in sync with upstream and may lack newer upstream features or fixes. To get the latest upstream changes, see [stickerdaniel/linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server).

## License

Apache 2.0 (same as upstream). See [LICENSE](LICENSE).

Use in accordance with [LinkedIn's Terms of Service](https://www.linkedin.com/legal/user-agreement).
