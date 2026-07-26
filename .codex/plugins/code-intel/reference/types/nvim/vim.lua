---@meta

---@class VimApi
---@field nvim_create_autocmd fun(event: string|string[], opts: table): integer
---@field nvim_create_augroup fun(name: string, opts: table): integer
---@field nvim_get_current_buf fun(): integer

---@class VimKeymap
---@field set fun(mode: string|string[], lhs: string, rhs: string|function, opts?: table)

---@class VimLsp
---@field buf table
---@field config fun(name: string, config: table)
---@field enable fun(name: string|string[])

---@class VimFn
---@field stdpath fun(name: string): string

---@class VimGlobal
---@field api VimApi
---@field keymap VimKeymap
---@field lsp VimLsp
---@field fn VimFn
---@field g table
---@field opt table
---@field notify fun(msg: string, level?: integer, opts?: table)

---@type VimGlobal
vim = vim or {}
