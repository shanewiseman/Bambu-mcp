# MCP client guide

Bambu MCP supports stdio for a client-owned local process and Streamable HTTP for
a long-running service. Tool results are JSON. Consequential tools return or
consume explicit job IDs, artifact IDs, plan digests, sequence IDs, and approval
tokens so clients can show evidence rather than infer success.

## Streamable HTTP

Connect to `http://127.0.0.1:8000/mcp` and send the API key as
`Authorization: Bearer <key>`. A representative client configuration is:

```json
{
  "mcpServers": {
    "bambu": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer ${BAMBU_MCP_API_KEY}"
      }
    }
  }
}
```

Use the exact schema supported by your MCP client; header/environment expansion
varies. Do not embed the key in a committed configuration.

## Stdio

```json
{
  "mcpServers": {
    "bambu": {
      "command": "/absolute/path/to/.venv/bin/bambu-mcp",
      "args": ["stdio"],
      "env": {
        "BAMBU_MCP_DATABASE_URL": "sqlite:////absolute/path/data/bambu-mcp.db",
        "BAMBU_MCP_ARTIFACT_ROOT": "/absolute/path/artifacts",
        "BAMBU_MCP_CREDENTIAL_KEY_FILE": "/secure/path/credential_key.txt"
      }
    }
  }
}
```

The stdio process must write protocol messages only to stdout; direct operational
logs belong on stderr. A single process should own a SQLite database.

## Recommended interaction

1. List/register a printer and call discovery/status resources.
2. Upload a model through `/api/v1/artifacts`; pass only its SHA-256 ID to MCP.
3. Call `prepare_print_pipeline` or `submit_stl_pipeline`.
4. Render the immutable plan to the human. Never automatically approve because a
   previous plan looked similar.
5. On explicit confirmation, call `approve_print_plan` and immediately pass the
   returned token to `execute_print_pipeline`.
6. Display transition events and MQTT sequence/result evidence. Treat tool errors
   as final until the operator inspects state; do not retry mutations blindly.

For cancellation, heating, motion, material movement, calibration, file changes,
or experimental calls, request an action approval using the identical operation
name and parameters, then call the target tool once. A changed parameter set is
correctly rejected.

## Resources

- `bambu://printers/{id}/status`
- `bambu://printers/{id}/capabilities`
- `bambu://printers/{id}/ams`
- `bambu://printers/{id}/hms`
- `bambu://printers/{id}/files`
- `bambu://jobs/{id}` and `/events`
- `bambu://artifacts/{sha256}`
- `bambu://protocol/capability-matrix`

See the [generated tool reference](generated/mcp-tools.md) for all inputs.
