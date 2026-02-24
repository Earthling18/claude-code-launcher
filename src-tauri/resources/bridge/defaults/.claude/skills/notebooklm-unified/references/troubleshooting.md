# NotebookLM Unified Skill - Troubleshooting Guide

## Quick Fix Table

| Error | Solution |
|-------|----------|
| Connection timeout | Check proxy configuration |
| Authentication failed | Set proxy, then `notebooklm login` |
| Document can't be parsed | Claude parse to Markdown, then upload |
| Generation timeout | `notebooklm artifact list` to check status |
| API returned no data | Check if `use <ID>` was run after `create` |
| source add fails after create | Must `notebooklm use <ID>` first |
| Query returns no answer | Verify notebook has content sources |
| Rate limit (50/day) | Wait or switch Google account |
| Notebook library corrupted | Backup + delete `~/.notebooklm/library.json` |
| `RPC GET_NOTEBOOK failed` | ID 被截断，用 `COLUMNS=200 notebooklm list` 获取完整 UUID |
| `pip externally-managed-environment` | 必须用 venv 内的 pip，不要用系统 pip |
| `venv/bin/activate` not found | 运行 `python3 $SKILL_DIR/install.py`（Windows 用 `python`） |

## Authentication Issues

### Not authenticated
```
Error: Not authenticated
```

**Solution:**
```bash
# Set proxy first
export http_proxy=<PROXY>
export https_proxy=<PROXY>

# Login
notebooklm login

# Verify
notebooklm list
```

### Authentication expired
**Solution:**
```bash
# Re-login
export http_proxy=<PROXY>
export https_proxy=<PROXY>
notebooklm login
```

### Google blocks login
**Solution:**
1. Use a dedicated Google account
2. Complete login in the browser window that opens
3. Wait for the NotebookLM homepage to load before pressing Enter

## Proxy / Network Issues

### Connection timeout
```bash
# Check if proxy is running
lsof -i -P | grep -i clash | head -5

# Common proxy ports
# Clash: 7890
# V2Ray: 10808
# Surge: 1087

# Set proxy
export http_proxy=<PROXY>
export https_proxy=<PROXY>

# Verify connectivity
curl -I https://notebooklm.google.com
```

## Generation Issues

### Generation hangs or times out
```bash
# Check artifact status
notebooklm artifact list

# Wait for specific artifact
notebooklm artifact wait <artifact_id>
```

### "API returned no data for URL"
This usually means you haven't switched to the correct notebook after creating it.

```bash
# After creating a notebook, MUST switch to it
notebooklm create "Title"
# Output: Created notebook: <ID> - Title

notebooklm use <ID>  # <-- CRITICAL STEP
notebooklm source add "URL"
```

### Document parsing failure
For encrypted/internal documents:
1. Have Claude read and parse the document
2. Save as Markdown to `/tmp/`
3. Upload the Markdown file: `notebooklm source add /tmp/file.md`

## Query Issues

### Query returns empty or fails
1. Verify notebook has content sources: `notebooklm list` (check source count)
2. Check authentication: `notebooklm list`
3. Check proxy is set
4. Try a simpler question to test

### Query timeout
```bash
# Check network
curl -I https://notebooklm.google.com

# Retry with proxy verified
export http_proxy=<PROXY>
export https_proxy=<PROXY>
notebooklm ask "Simple test question"
```

## Rate Limiting

### Rate limit exceeded (50 queries/day for free accounts)

**Option 1: Wait**
- Limit resets around midnight PST

**Option 2: Switch accounts**
```bash
# Login with different Google account
notebooklm login
```

## Notebook Library Issues

### Corrupted library.json
```bash
# Backup
cp ~/.notebooklm/library.json ~/.notebooklm/library.json.backup

# Reset
rm ~/.notebooklm/library.json

# Re-add notebooks
python scripts/notebook_library.py add --url ... --name ... --description ... --topics ...
```

### Notebook not found in library
```bash
# List all notebooks
python scripts/notebook_library.py list

# Search
python scripts/notebook_library.py search --query "keyword"

# Add if missing
python scripts/notebook_library.py add --url "URL" --name "Name" --description "Desc" --topics "topics"
```

## Environment Issues

### Dependencies missing
```bash
# Run cross-platform install script (creates venv automatically)
python3 install.py    # macOS/Linux
python install.py     # Windows
```

### PEP 668 (externally-managed-environment)
macOS Homebrew Python 3.12+ 禁止直接 `pip3 install`。必须使用 venv：
```bash
# install.py 会自动创建 venv，手动创建：
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

### Check full environment
```bash
python3 check_env.py  # macOS/Linux
python check_env.py   # Windows
```

## Recovery Procedures

### Complete reset
```bash
# Backup library
cp ~/.notebooklm/library.json ~/library.backup.json 2>/dev/null

# Clear auth state
rm -rf ~/.notebooklm/storage_state.json

# Re-authenticate
export http_proxy=<PROXY>
export https_proxy=<PROXY>
notebooklm login

# Restore library
cp ~/library.backup.json ~/.notebooklm/library.json 2>/dev/null
```

## Error Messages Reference

### Authentication Errors
| Error | Cause | Solution |
|-------|-------|----------|
| Not authenticated | No valid auth | `notebooklm login` |
| Authentication expired | Session old | `notebooklm login` |
| Invalid credentials | Wrong account | Check Google account |

### Generation Errors
| Error | Cause | Solution |
|-------|-------|----------|
| API returned no data | Wrong notebook selected | `notebooklm use <ID>` |
| Source add failed | Notebook not switched | `create` then `use <ID>` |
| Generation timeout | Large content | `artifact wait <ID>` |
| Document parse error | Encrypted file | Claude parse to Markdown |

### Query Errors
| Error | Cause | Solution |
|-------|-------|----------|
| No response | Empty notebook | Add sources first |
| Timeout | Network issue | Check proxy |
| Rate limited | 50/day exceeded | Wait or switch account |

### Library Errors
| Error | Cause | Solution |
|-------|-------|----------|
| Notebook not found | Invalid ID | `notebook_library.py list` |
| Duplicate ID | Name collision | Use different name |
| JSON decode error | Corrupted file | Backup + reset library.json |
