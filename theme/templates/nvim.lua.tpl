-- neovim colorscheme: theme "{{ theme }}" ({{ meta.name }}), written by `bromigos theme set`.
-- Don't edit. `dofile` it (or `require` it through bromigos-apps' colors/bromigos.lua,
-- which also re-applies it when the theme changes): it sets every highlight group and
-- returns its colours, so a plugin spec can read them.
local c = {
  background = "{{ background }}", void = "{{ void }}", panel = "{{ panel }}", selection = "{{ selection }}",
  primary = "{{ primary }}", soft = "{{ soft }}", dim = "{{ dim }}", text = "{{ text }}",
  muted = "{{ muted }}", faint = "{{ faint }}", warn = "{{ warn }}", danger = "{{ danger }}",
  warn_surface = "{{ warn_surface }}", danger_surface = "{{ danger_surface }}", danger_text = "{{ danger_text }}",
  cyan = "{{ cyan }}", gold = "{{ gold }}", white = "{{ white }}", rust = "{{ rust }}",
  blue = "{{ terminal.color4 }}", magenta = "{{ terminal.color5 }}", bright_blue = "{{ terminal.color12 }}",
  bright_magenta = "{{ terminal.color13 }}",
}
local M = { colors = c, name = "bromigos", theme = "{{ theme }}" }

function M.apply()
  vim.g.colors_name = "bromigos"
  vim.o.background = "{{ meta.mode }}"
  local hl = function(group, spec) vim.api.nvim_set_hl(0, group, spec) end
  -- the editor
  hl("Normal", { fg = c.text, bg = c.background })
  hl("NormalNC", { fg = c.text, bg = c.background })
  hl("NormalFloat", { fg = c.text, bg = c.panel })
  hl("FloatBorder", { fg = c.dim, bg = c.panel })
  hl("FloatTitle", { fg = c.primary, bg = c.panel, bold = true })
  hl("Cursor", { fg = c.background, bg = c.primary })
  hl("CursorLine", { bg = c.panel })
  hl("CursorColumn", { bg = c.panel })
  hl("ColorColumn", { bg = c.panel })
  hl("LineNr", { fg = c.faint })
  hl("CursorLineNr", { fg = c.primary, bold = true })
  hl("SignColumn", { bg = c.background })
  hl("Folded", { fg = c.muted, bg = c.panel })
  hl("FoldColumn", { fg = c.faint })
  hl("NonText", { fg = c.faint })
  hl("SpecialKey", { fg = c.faint })
  hl("Whitespace", { fg = c.faint })
  hl("EndOfBuffer", { fg = c.background })
  hl("Visual", { bg = c.selection })
  hl("VisualNOS", { bg = c.selection })
  hl("Search", { fg = c.background, bg = c.warn })
  hl("CurSearch", { fg = c.background, bg = c.primary })
  hl("IncSearch", { fg = c.background, bg = c.primary })
  hl("Substitute", { fg = c.background, bg = c.warn })
  hl("MatchParen", { fg = c.primary, bold = true, underline = true })
  hl("WinSeparator", { fg = c.selection })
  hl("VertSplit", { fg = c.selection })
  hl("StatusLine", { fg = c.soft, bg = c.panel })
  hl("StatusLineNC", { fg = c.muted, bg = c.panel })
  hl("TabLine", { fg = c.muted, bg = c.panel })
  hl("TabLineSel", { fg = c.background, bg = c.primary, bold = true })
  hl("TabLineFill", { bg = c.background })
  hl("WildMenu", { fg = c.background, bg = c.primary })
  hl("Pmenu", { fg = c.text, bg = c.panel })
  hl("PmenuSel", { fg = c.background, bg = c.primary })
  hl("PmenuSbar", { bg = c.selection })
  hl("PmenuThumb", { bg = c.dim })
  hl("Title", { fg = c.primary, bold = true })
  hl("Directory", { fg = c.cyan })
  hl("Question", { fg = c.primary })
  hl("MoreMsg", { fg = c.primary })
  hl("ModeMsg", { fg = c.soft, bold = true })
  hl("ErrorMsg", { fg = c.danger, bold = true })
  hl("WarningMsg", { fg = c.warn })
  hl("Conceal", { fg = c.muted })
  hl("SpellBad", { sp = c.danger, undercurl = true })
  hl("SpellCap", { sp = c.warn, undercurl = true })
  hl("SpellRare", { sp = c.magenta, undercurl = true })
  hl("SpellLocal", { sp = c.cyan, undercurl = true })
  -- syntax
  hl("Comment", { fg = c.muted, italic = true })
  hl("Constant", { fg = c.gold })
  hl("String", { fg = c.soft })
  hl("Character", { fg = c.soft })
  hl("Number", { fg = c.gold })
  hl("Boolean", { fg = c.gold })
  hl("Float", { fg = c.gold })
  hl("Identifier", { fg = c.text })
  hl("Function", { fg = c.primary })
  hl("Statement", { fg = c.cyan, bold = true })
  hl("Conditional", { fg = c.cyan })
  hl("Repeat", { fg = c.cyan })
  hl("Label", { fg = c.cyan })
  hl("Operator", { fg = c.soft })
  hl("Keyword", { fg = c.cyan, bold = true })
  hl("Exception", { fg = c.danger })
  hl("PreProc", { fg = c.magenta })
  hl("Include", { fg = c.magenta })
  hl("Define", { fg = c.magenta })
  hl("Macro", { fg = c.magenta })
  hl("Type", { fg = c.blue })
  hl("StorageClass", { fg = c.blue })
  hl("Structure", { fg = c.blue })
  hl("Typedef", { fg = c.blue })
  hl("Special", { fg = c.warn })
  hl("SpecialChar", { fg = c.warn })
  hl("Tag", { fg = c.primary })
  hl("Delimiter", { fg = c.muted })
  hl("SpecialComment", { fg = c.muted, bold = true })
  hl("Debug", { fg = c.danger })
  hl("Underlined", { fg = c.cyan, underline = true })
  hl("Ignore", { fg = c.faint })
  hl("Error", { fg = c.danger_text, bg = c.danger_surface })
  hl("Todo", { fg = c.background, bg = c.warn, bold = true })
  -- tree-sitter and LSP
  hl("@variable", { fg = c.text })
  hl("@variable.builtin", { fg = c.warn })
  hl("@property", { fg = c.soft })
  hl("@field", { fg = c.soft })
  hl("@parameter", { fg = c.text, italic = true })
  hl("@constructor", { fg = c.blue })
  hl("@punctuation", { fg = c.muted })
  hl("@string.escape", { fg = c.warn })
  hl("@text.title", { fg = c.primary, bold = true })
  hl("@text.uri", { fg = c.cyan, underline = true })
  hl("@tag.attribute", { fg = c.soft })
  hl("@lsp.type.namespace", { fg = c.magenta })
  hl("DiagnosticError", { fg = c.danger })
  hl("DiagnosticWarn", { fg = c.warn })
  hl("DiagnosticInfo", { fg = c.cyan })
  hl("DiagnosticHint", { fg = c.muted })
  hl("DiagnosticUnderlineError", { sp = c.danger, undercurl = true })
  hl("DiagnosticUnderlineWarn", { sp = c.warn, undercurl = true })
  hl("DiagnosticUnderlineInfo", { sp = c.cyan, undercurl = true })
  hl("DiagnosticUnderlineHint", { sp = c.muted, undercurl = true })
  hl("LspReferenceText", { bg = c.selection })
  hl("LspReferenceRead", { bg = c.selection })
  hl("LspReferenceWrite", { bg = c.selection, underline = true })
  -- diffs and git
  hl("DiffAdd", { fg = c.primary, bg = c.panel })
  hl("DiffChange", { fg = c.warn, bg = c.panel })
  hl("DiffDelete", { fg = c.danger, bg = c.danger_surface })
  hl("DiffText", { fg = c.background, bg = c.warn })
  hl("Added", { fg = c.primary })
  hl("Changed", { fg = c.warn })
  hl("Removed", { fg = c.danger })
  hl("GitSignsAdd", { fg = c.primary })
  hl("GitSignsChange", { fg = c.warn })
  hl("GitSignsDelete", { fg = c.danger })
  -- the plugins LazyVim ships
  hl("TelescopeBorder", { fg = c.dim, bg = c.panel })
  hl("TelescopeNormal", { fg = c.text, bg = c.panel })
  hl("TelescopeTitle", { fg = c.primary, bold = true })
  hl("TelescopeSelection", { fg = c.primary, bg = c.selection })
  hl("TelescopeMatching", { fg = c.warn, bold = true })
  hl("TelescopePromptPrefix", { fg = c.primary })
  hl("NvimTreeNormal", { fg = c.text, bg = c.background })
  hl("NeoTreeNormal", { fg = c.text, bg = c.background })
  hl("NeoTreeDirectoryIcon", { fg = c.cyan })
  hl("NeoTreeDirectoryName", { fg = c.cyan })
  hl("NeoTreeGitModified", { fg = c.warn })
  hl("NeoTreeGitAdded", { fg = c.primary })
  hl("NeoTreeGitDeleted", { fg = c.danger })
  hl("WhichKey", { fg = c.primary })
  hl("WhichKeyGroup", { fg = c.cyan })
  hl("WhichKeyDesc", { fg = c.text })
  hl("WhichKeySeparator", { fg = c.muted })
  hl("LazyNormal", { fg = c.text, bg = c.panel })
  hl("LazyH1", { fg = c.background, bg = c.primary, bold = true })
  hl("LazyButton", { fg = c.soft, bg = c.selection })
  hl("LazyButtonActive", { fg = c.background, bg = c.primary, bold = true })
  hl("MasonNormal", { fg = c.text, bg = c.panel })
  hl("NotifyINFOBorder", { fg = c.dim })
  hl("NotifyINFOTitle", { fg = c.primary })
  hl("NotifyWARNBorder", { fg = c.warn })
  hl("NotifyWARNTitle", { fg = c.warn })
  hl("NotifyERRORBorder", { fg = c.danger })
  hl("NotifyERRORTitle", { fg = c.danger })
  hl("CmpItemAbbrMatch", { fg = c.primary, bold = true })
  hl("CmpItemAbbrMatchFuzzy", { fg = c.primary })
  hl("CmpItemKind", { fg = c.cyan })
  hl("CmpItemMenu", { fg = c.muted })
  hl("IndentBlanklineChar", { fg = c.selection })
  hl("IblIndent", { fg = c.selection })
  hl("IblScope", { fg = c.dim })
  hl("SnacksIndent", { fg = c.selection })
  hl("SnacksIndentScope", { fg = c.dim })
  hl("SnacksPickerBorder", { fg = c.dim, bg = c.panel })
  hl("SnacksPickerMatch", { fg = c.warn, bold = true })
  hl("MiniStatuslineModeNormal", { fg = c.background, bg = c.primary, bold = true })
  hl("MiniStatuslineModeInsert", { fg = c.background, bg = c.cyan, bold = true })
  hl("MiniStatuslineModeVisual", { fg = c.background, bg = c.warn, bold = true })
  hl("MiniStatuslineModeReplace", { fg = c.background, bg = c.danger, bold = true })
  hl("MiniStatuslineModeCommand", { fg = c.background, bg = c.gold, bold = true })
  -- terminal
  vim.g.terminal_color_0 = "{{ terminal.color0 }}"
  vim.g.terminal_color_1 = "{{ terminal.color1 }}"
  vim.g.terminal_color_2 = "{{ terminal.color2 }}"
  vim.g.terminal_color_3 = "{{ terminal.color3 }}"
  vim.g.terminal_color_4 = "{{ terminal.color4 }}"
  vim.g.terminal_color_5 = "{{ terminal.color5 }}"
  vim.g.terminal_color_6 = "{{ terminal.color6 }}"
  vim.g.terminal_color_7 = "{{ terminal.color7 }}"
  vim.g.terminal_color_8 = "{{ terminal.color8 }}"
  vim.g.terminal_color_9 = "{{ terminal.color9 }}"
  vim.g.terminal_color_10 = "{{ terminal.color10 }}"
  vim.g.terminal_color_11 = "{{ terminal.color11 }}"
  vim.g.terminal_color_12 = "{{ terminal.color12 }}"
  vim.g.terminal_color_13 = "{{ terminal.color13 }}"
  vim.g.terminal_color_14 = "{{ terminal.color14 }}"
  vim.g.terminal_color_15 = "{{ terminal.color15 }}"
end

M.apply()
return M
