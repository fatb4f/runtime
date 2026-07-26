---@meta

---@alias WeztermEvent
---| "gui-startup"
---| "window-config-reloaded"
---| "update-right-status"
---| "format-window-title"
---| "format-tab-title"
---| "user-var-changed"

---@class WeztermEventRegistry
---@field on fun(event: WeztermEvent|string, callback: function)

return {}
