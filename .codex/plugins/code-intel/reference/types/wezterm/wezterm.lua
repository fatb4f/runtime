---@meta

---@class WeztermAction

---@class WeztermPane
---@field get_current_working_dir fun(self: WeztermPane): string|nil

---@class WeztermWindow
---@field active_pane fun(self: WeztermWindow): WeztermPane
---@field set_right_status fun(self: WeztermWindow, status: string)

---@class WeztermModule
---@field action fun(action: table): WeztermAction
---@field config_builder fun(): WeztermConfig
---@field font fun(name: string, opts?: table): table
---@field format fun(items: table[]): string
---@field on fun(event: string, callback: function)

local wezterm = {}

return wezterm
