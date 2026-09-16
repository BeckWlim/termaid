# Editor and subprocess integrations

Use styled JSON for rendered content and JSON diagnostics for errors:

```sh
termaid --format styled-json --diagnostics-format json \
  --width 120 --strict-width --fit-mode reflow --max-height 4096
```

Pass Mermaid source on stdin. Stdout contains the existing version-1 styled
document on success. Stderr contains one JSON object per line for each diagnostic;
parse each line separately. Ordinary successful renders produce no diagnostics.
The default diagnostic format remains human-readable text.

For example, a diagram that cannot fit the requested width reports:

```json
{"version":1,"severity":"error","code":"width_exceeded","message":"diagram is 146 cols wide but target is 120. Try: less -S, or use 'graph TD' for vertical layout.","details":{"actual_width":146,"max_width":120},"exit_code":2}
```

The process exits with code 2 and emits no rendered content. Render failures and
constraint failures are checked before opening an `--output` file, preserving any
previous output. An output I/O failure can still leave a partially written file.

## Diagnostic contract, version 1

| Field | Meaning |
| --- | --- |
| `version` | Diagnostic schema version, currently `1` |
| `severity` | `error` or `warning` |
| `code` | Stable identifier for consumer decisions |
| `message` | Human-readable explanation; wording is not a machine interface |
| `details` | Code-specific data with string or integer values |
| `exit_code` | Exit status for this error; `0` for a nonfatal warning |

| Code | Exit status | Details |
| --- | --- | --- |
| `invalid_arguments` | 2 (1 for an unknown demo name) | `{}` |
| `input_missing` | 1 | `{}` |
| `input_not_found` | 1 | `path` |
| `input_read_failed` | 1 | `path` for file input; absent for stdin |
| `input_empty` | 1 | `{}` |
| `input_conversion_failed` | 1 | `{}` |
| `render_empty` | 1 | `{}` |
| `render_failed` | 1 | `exception_type` |
| `width_exceeded` | 2 with `--strict-width`; otherwise warning, 0 | `actual_width`, `max_width`, in terminal cells |
| `height_exceeded` | 2 | `actual_height`, `max_height`, in rows |
| `output_write_failed` | 1 | `path`, or `<stdout>` |
| `dependency_missing` | 1 | `dependency` |

Consumers should check the process exit status, tolerate unknown codes and extra
fields, and retain a text fallback for older termaid versions. A warning does not
imply process failure; a later error may follow it. When both width and height
limits fail, width is reported first. The measured size describes the selected
layout, not a proven minimum size for the diagram.

Parsers remain permissive: an unsupported or empty diagram may produce
`render_empty`, but this protocol does not add comprehensive Mermaid syntax
validation. Python rendering functions continue to raise their original
exceptions; diagnostic serialization occurs at the CLI boundary.

## Neovim callback example

An adapter can turn process diagnostics into `User` events. Associate the callback
with the originating buffer and render request in your plugin; discard stale
callbacks before publishing events.

```lua
local source = 'graph LR\n  A --> B'
vim.system({
  'termaid', '--format', 'styled-json', '--diagnostics-format', 'json',
  '--width', '120', '--strict-width', '--fit-mode', 'reflow',
}, { stdin = source, text = true, timeout = 8000 }, function(result)
  vim.schedule(function()
    for line in (result.stderr or ''):gmatch('[^\r\n]+') do
      local decoded, diagnostic = pcall(vim.json.decode, line)
      if decoded and type(diagnostic) == 'table' and diagnostic.version == 1 then
        vim.api.nvim_exec_autocmds('User', {
          pattern = 'TermaidDiagnostic', data = diagnostic,
        })
      else
        vim.notify(line, vim.log.levels.WARN)
      end
    end
    if result.code == 0 then
      -- Feed result.stdout into your existing styled-document decoder.
    end
  end)
end)

vim.api.nvim_create_autocmd('User', {
  pattern = 'TermaidDiagnostic',
  callback = function(event)
    local diagnostic = event.data
    if diagnostic.code == 'width_exceeded' then
      -- Offer a wider preview using diagnostic.details.actual_width.
    end
    local level = diagnostic.severity == 'error'
      and vim.log.levels.ERROR or vim.log.levels.WARN
    vim.notify(diagnostic.message, level)
  end,
})
```

The event names above are defined by the adapter, not by the termaid executable.
Process-start failures, externally enforced timeouts, and signal termination must
be reported by the host: a process that cannot start or is killed cannot emit a
diagnostic. Keep the host's existing exit-status and output-validation checks.
