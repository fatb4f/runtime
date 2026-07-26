---@meta

---@class WeztermConfig
---@field automatically_reload_config? boolean
---@field color_scheme? string
---@field default_prog? string[]
---@field font? table
---@field font_size? number
---@field keys? table[]
---@field leader? table
---@field window_background_opacity? number
---@field window_decorations? string
---@field window_padding? table
---@field use_fancy_tab_bar? boolean

---@return WeztermConfig
local function config_builder()
  return {}
end

return config_builder
