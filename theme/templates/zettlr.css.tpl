/* Zettlr's colours: theme "{{ theme }}" ({{ meta.name }}), written by `bromigos theme set`.
   Don't edit. The theme-set hook copies this between the bromigOS markers in
   ~/.config/Zettlr/custom.css and keeps the rest of that file, which is yours.
   Zettlr reads custom.css when it starts. Rules here use !important so they win over
   every Zettlr display theme; a rule of yours after the block needs it too. */
{%- if meta.mode == "light" %}
{%- set ramp = [background, panel, selection, faint, muted, dim, soft, text] %}
{%- else %}
{%- set ramp = [text, soft, muted, faint, dim, selection, panel, background] %}
{%- endif %}
:root {
  color-scheme: {{ meta.mode }} !important;
  accent-color: {{ primary }} !important;
  --bromigos-background: {{ background }};
  --bromigos-void: {{ void }};
  --bromigos-panel: {{ panel }};
  --bromigos-selection: {{ selection }};
  --bromigos-primary: {{ primary }};
  --bromigos-soft: {{ soft }};
  --bromigos-dim: {{ dim }};
  --bromigos-text: {{ text }};
  --bromigos-muted: {{ muted }};
  --bromigos-faint: {{ faint }};
  --bromigos-warn: {{ warn }};
  --bromigos-danger: {{ danger }};
  --bromigos-link: {{ cyan }};
  --bromigos-font: "Geist Mono", ui-monospace, monospace;
  --bromigos-code-font: "Geist Mono", ui-monospace, monospace;

  /* Zettlr's own colours: the accent (on Linux, Zettlr's green), its greys and the
     folder colours */
  --system-accent-color: {{ primary }} !important;
  --system-accent-color-contrast: {{ background }} !important;
{%- for value in ramp %}
  --grey-{{ loop.index0 }}: {{ value }} !important;
{%- endfor %}
  --accent-blue: {{ terminal.color4 }} !important;
  --accent-purple: {{ terminal.color5 }} !important;
  --accent-rose: {{ terminal.color13 }} !important;
  --accent-red: {{ danger }} !important;
  --accent-orange: {{ terminal.color11 }} !important;
  --accent-yellow: {{ warn }} !important;
  --accent-green: {{ terminal.color2 }} !important;
  --red-2: {{ danger }} !important;
}

/* ---- the window */
body, body.dark {
  background-color: {{ background }} !important;
  color: {{ text }} !important;
  font-family: var(--bromigos-font) !important;

  /* callouts (> [!NOTE] and the like): Zettlr sets these on the body */
  --zettlr-note-color: {{ muted }} !important;
  --zettlr-tip-color: {{ primary }} !important;
  --zettlr-important-color: {{ terminal.color5 }} !important;
  --zettlr-warning-color: {{ warn }} !important;
  --zettlr-caution-color: {{ danger }} !important;
  --zettlr-note-bg: {{ panel }} !important;
  --zettlr-tip-bg: {{ selection }} !important;
  --zettlr-important-bg: {{ panel }} !important;
  --zettlr-warning-bg: {{ warn_surface }} !important;
  --zettlr-caution-bg: {{ danger_surface }} !important;
}
body a, body.dark a { color: {{ cyan }} !important; }
body div#window-content, body.dark div#window-content { background-color: {{ background }} !important; }
body ::selection { background-color: {{ selection }} !important; color: {{ text }} !important; }
body label, body input, body select, body textarea, body button { font-family: var(--bromigos-font) !important; }

/* ---- the menu bar and title bar */
body #menubar, body div#titlebar {
  background-color: {{ panel }} !important;
  color: {{ soft }} !important;
  border-bottom: 1px solid {{ selection }} !important;
}
body #menubar div.top-level-item:hover { background-color: {{ selection }} !important; color: {{ primary }} !important; }

/* ---- the toolbar */
body div#toolbar {
  background-color: {{ panel }} !important;
  color: {{ soft }} !important;
  border-bottom: 1px solid {{ selection }} !important;
}
body div#toolbar button {
  background-color: transparent !important;
  color: {{ soft }} !important;
  border: 1px solid {{ selection }} !important;
}
body div#toolbar button:hover, body div#toolbar button.toolbar-overflow, body div#toolbar button.active {
  background-color: {{ selection }} !important;
  color: {{ primary }} !important;
  border-color: {{ dim }} !important;
}
body div#toolbar .toolbar-text, body div#toolbar span.toolbar-label { color: {{ muted }} !important; }

/* ---- the file manager: the tree, the file list and their headers */
body #file-manager, body #file-tree, body #file-list,
body div.list-item-wrapper, body div.list-item-wrapper div.list-item, body div.list-item-wrapper div.list-item div.filename div.date {
  background-color: {{ panel }} !important;
  color: {{ text }} !important;
}
body div.list-item-wrapper div.list-item { border-bottom-color: {{ selection }} !important; }
body div.list-item-wrapper div.list-item div.date { color: {{ muted }} !important; }
body div.list-item-wrapper div.list-item.active, body div.list-item-wrapper div.list-item.active div.filename div.date {
  background-color: {{ dim }} !important;
  color: {{ background }} !important;
}
body div.list-item-wrapper div.list-item.selected, body div.list-item-wrapper div.list-item.selected div.filename div.date {
  background-color: {{ selection }} !important;
  color: {{ primary }} !important;
}
body div.list-item-wrapper div.list-item div.meta-info .badge { background-color: {{ selection }} !important; color: {{ soft }} !important; }
body #directories-dirs-header, body #directories-files-header {
  color: {{ muted }} !important;
  border-bottom: 1px solid {{ selection }} !important;
}
body #file-tree .close-all { background-color: {{ selection }} !important; color: {{ soft }} !important; }
body #file-manager .file-manager-filter { background-color: {{ panel }} !important; border-color: {{ selection }} !important; }
body #file-manager .file-manager-filter .file-manager-filter-input {
  background-color: {{ void }} !important;
  color: {{ text }} !important;
  border: 1px solid {{ selection }} !important;
}
body #file-manager .file-manager-filter .file-manager-filter-input:focus { border-color: {{ primary }} !important; }
body #file-manager #arrow-button { background-color: {{ selection }} !important; color: {{ primary }} !important; }
body div.tree-item-container .tree-item { color: {{ text }} !important; }
body div.tree-item-container .tree-item.directory:not(.collapsed) { background-color: {{ panel }} !important; }
body div.tree-item-container .tree-item.project { color: {{ warn }} !important; }
body div.tree-item-container .tree-item .display-text.highlight { background-color: {{ selection }} !important; color: {{ primary }} !important; }
body div.tree-item-container .tree-item.active .display-text { background-color: {{ dim }} !important; color: {{ background }} !important; }
body div.tree-item-container .tree-item.selected .display-text { background-color: {{ selection }} !important; color: {{ primary }} !important; }
body div.tree-item-container .tree-item input.filename-input { background-color: {{ void }} !important; color: {{ text }} !important; }
body ::placeholder { color: {{ faint }} !important; }

/* ---- the sidebar: contents, related files, references */
body div#sidebar, body.dark div#sidebar {
  background-color: {{ panel }} !important;
  color: {{ text }} !important;
}
body div#sidebar div.toc-level { color: {{ dim }} !important; }
body div#sidebar div.toc-entry-active { color: {{ primary }} !important; }
body div#sidebar div.related-files-container div.related-file:hover { background-color: {{ selection }} !important; }
body div.split-view div.view.view-border { border-color: {{ selection }} !important; }

/* ---- the tabs */
body div.document-tablist-wrapper div.scroller,
body div.tab-container {
  background-color: {{ panel }} !important;
  color: {{ muted }} !important;
  border-color: {{ selection }} !important;
}
body div.tab-container { border-bottom: 1px solid {{ selection }} !important; }
body div.tab-container div[role="tab"] {
  background-color: {{ panel }} !important;
  color: {{ muted }} !important;
  border-color: {{ selection }} !important;
  font-family: var(--bromigos-font) !important;
}
body div.tab-container div[role="tab"]:hover, body div.document-tablist-wrapper div.scroller:hover {
  background-color: {{ selection }} !important;
  color: {{ soft }} !important;
}
body div.tab-container div[role="tab"].active {
  background-color: {{ background }} !important;
  color: {{ primary }} !important;
  border-bottom: 3px solid {{ primary }} !important;
}
body div.tab-container div[role="tab"].modified .filename::before { color: {{ warn }} !important; }
body div.tab-container div[role="tab"] .close:hover { background-color: {{ dim }} !important; color: {{ background }} !important; }

/* ---- the editor: Zettlr's editor variables, for every display theme */
body .cm-editor, body.dark .cm-editor {
  --zettlr-editor-primary-color: {{ primary }} !important;
  --zettlr-editor-secondary-color: {{ cyan }} !important;
  --zettlr-editor-scroller-color: {{ text }} !important;
  --zettlr-editor-scroller-bg: {{ background }} !important;
  --zettlr-editor-selection-color: {{ selection }}cc !important;
  --zettlr-editor-highlight-color: {{ warn }}66 !important;
  --zettlr-editor-font: var(--bromigos-font) !important;
  --zettlr-editor-code-font: var(--bromigos-code-font) !important;
  --zettlr-editor-citation-color: {{ muted }} !important;
  --zettlr-editor-citation-bg: {{ panel }} !important;
  --zettlr-editor-code-color: {{ soft }} !important;
  --zettlr-editor-code-bg: {{ panel }} !important;
  --zettlr-editor-escape-color: {{ muted }} !important;
  --zettlr-editor-accent-color: {{ background }} !important;
  --zettlr-editor-accent-bg: {{ dim }} !important;
  --zettlr-editor-error-color: {{ danger }} !important;
  /* code blocks: the terminal's colours */
  --zettlr-editor-code-base-0: {{ muted }} !important;
  --zettlr-editor-code-base-1: {{ text }} !important;
  --zettlr-editor-code-base-2: {{ soft }} !important;
  --zettlr-editor-code-base-3: {{ background }} !important;
  --zettlr-editor-code-base-00: {{ muted }} !important;
  --zettlr-editor-code-base-01: {{ faint }} !important;
  --zettlr-editor-code-base-02: {{ text }} !important;
  --zettlr-editor-code-base-03: {{ panel }} !important;
  --zettlr-editor-code-yellow: {{ terminal.color3 }} !important;
  --zettlr-editor-code-orange: {{ terminal.color11 }} !important;
  --zettlr-editor-code-red: {{ terminal.color1 }} !important;
  --zettlr-editor-code-magenta: {{ terminal.color5 }} !important;
  --zettlr-editor-code-violet: {{ terminal.color13 }} !important;
  --zettlr-editor-code-blue: {{ terminal.color4 }} !important;
  --zettlr-editor-code-cyan: {{ terminal.color6 }} !important;
  --zettlr-editor-code-green: {{ terminal.color2 }} !important;
  background-color: {{ background }} !important;
  caret-color: {{ primary }} !important;
}
body .main-editor-wrapper, body.dark .main-editor-wrapper { background-color: {{ background }} !important; }
body .editor-pane .editor-container .empty-pane { background-color: {{ background }} !important; }
body .cm-editor .cm-scroller { background-color: {{ background }} !important; color: {{ text }} !important; }
body .cm-editor .cm-gutters { background-color: {{ background }} !important; color: {{ faint }} !important; border-right-color: transparent !important; }
body .cm-editor .cm-heading-gutter .cm-gutterElement, body .cm-editor .cm-heading-gutter .cm-gutterElement div { color: {{ faint }} !important; }
body .cm-editor .cm-cursor, body .cm-editor .cm-cursor-primary { border-left-color: {{ primary }} !important; background: {{ primary }} !important; }
body .cm-editor .cm-selectionBackground, body .cm-editor.cm-focused .cm-selectionBackground { background: {{ selection }}cc !important; }
body .cm-editor .cm-activeLine { background-color: transparent !important; }
/* headings */
body .cm-editor [class^="cm-header-"], body .cm-editor [class*=" cm-header-"] { color: {{ primary }} !important; }
body .cm-editor .cm-header-3, body .cm-editor .cm-header-4,
body .cm-editor .cm-header-5, body .cm-editor .cm-header-6 { color: {{ soft }} !important; }
body .cm-editor .cm-strong { color: {{ soft }} !important; }
/* links, tags, quotes */
body .cm-editor .cm-link, body .cm-editor .cm-url, body .cm-editor .cm-zkn-link { color: {{ cyan }} !important; }
body .cm-editor .cm-zkn-tag { color: {{ primary }} !important; }
body .cm-editor .cm-quote { color: {{ soft }} !important; }
body .cm-editor .blockquote-wrapper { border-left-color: {{ dim }} !important; }
body .cm-editor .cm-hr { color: {{ dim }} !important; }
/* code */
body .cm-editor .code-block-line-background, body .cm-editor .inline-code-background { background-color: {{ panel }} !important; }
body .cm-editor .cm-monospace { color: {{ soft }} !important; font-family: var(--bromigos-code-font) !important; }
body .cm-editor .code { color: {{ text }} !important; }
/* tables */
body .cm-editor div.cm-table-editor-widget-wrapper table td,
body .cm-editor div.cm-table-editor-widget-wrapper table th { color: {{ text }} !important; border-color: {{ selection }} !important; }
body .cm-editor div.cm-table-editor-widget-wrapper table th { background-color: {{ panel }} !important; color: {{ primary }} !important; }

/* ---- the editor's status bar, panels and pop-ups */
body .cm-editor .cm-statusbar, body .cm-editor .cm-panels, body .cm-editor .cm-tooltip {
  background-color: {{ panel }} !important;
  color: {{ muted }} !important;
  border-color: {{ selection }} !important;
}
body .cm-editor .cm-panels-bottom { border-top: 1px solid {{ selection }} !important; }
body .cm-editor .cm-statusbar .cm-statusbar-item:not(:first-child) { border-left-color: {{ selection }} !important; }
body .cm-editor .cm-statusbar button, body .cm-editor .cm-panel .cm-button {
  background-color: transparent !important;
  background-image: none !important;
  color: {{ soft }} !important;
  border: 1px solid {{ selection }} !important;
}
body .cm-editor .cm-tooltip-autocomplete ul li[aria-selected] { background-color: {{ selection }} !important; color: {{ primary }} !important; }
body .cm-editor .cm-formatting-bar { background-color: {{ panel }} !important; border-color: {{ selection }} !important; }
body .cm-editor .cm-formatting-bar button.formatting-toolbar-button { color: {{ soft }} !important; }
body .cm-editor .cm-formatting-bar button.formatting-toolbar-button:hover { background-color: {{ selection }} !important; }
body div#statusbar { background-color: {{ panel }} !important; color: {{ muted }} !important; border-top: 1px solid {{ selection }} !important; }

/* ---- dialogs: pop-overs, menus, tooltips, the preferences and other windows */
body .popover, body.dark .popover {
  background-color: {{ panel }} !important;
  color: {{ text }} !important;
  border: 1px solid {{ dim }} !important;
}
body .popover hr { border-color: {{ selection }} !important; }
body .popover-arrow.up { border-bottom-color: {{ dim }} !important; }
body .popover-arrow.down { border-top-color: {{ dim }} !important; }
body .popover-arrow.left { border-right-color: {{ dim }} !important; }
body .popover-arrow.right { border-left-color: {{ dim }} !important; }
body div.application-menu, body.dark div.application-menu {
  background-color: {{ panel }} !important;
  color: {{ text }} !important;
  border: 1px solid {{ dim }} !important;
  font-family: var(--bromigos-font) !important;
}
body div.application-menu div.menu-item:not(.separator):not(.disabled):hover { background-color: {{ selection }} !important; color: {{ primary }} !important; }
body div.application-menu div.menu-item.disabled, body div.application-menu div.menu-item div.after-element { color: {{ faint }} !important; }
body div.application-menu div.menu-item.separator { background-color: {{ selection }} !important; border-color: {{ selection }} !important; }
body .tippy-box { background-color: {{ void }} !important; color: {{ text }} !important; border: 1px solid {{ dim }} !important; }
body .tippy-box .tippy-arrow { color: {{ dim }} !important; }
body div.tab-list { background-color: {{ panel }} !important; color: {{ muted }} !important; border-bottom-color: {{ selection }} !important; }
body div.tab-list button[role="tab"] { background-color: transparent !important; color: {{ muted }} !important; }
body div.tab-list button[role="tab"]:hover { background-color: {{ selection }} !important; color: {{ soft }} !important; }
body div.tab-list button[role="tab"].active { background-color: {{ selection }} !important; color: {{ primary }} !important; }
body input, body select, body textarea, body button,
body.dark input, body.dark select, body.dark textarea, body.dark button {
  background-color: {{ void }} !important;
  color: {{ text }} !important;
  border-color: {{ selection }} !important;
}
body input:focus, body select:focus, body textarea:focus { border-color: {{ primary }} !important; }
body button:hover { background-color: {{ selection }} !important; }
body button.primary, body div#statusbar button.primary {
  background-color: {{ primary }} !important;
  background-image: none !important;
  border-color: {{ primary }} !important;
  color: {{ background }} !important;
}
body div#global-search-pane div.search-result-container { border-bottom-color: {{ selection }} !important; }
body div#global-search-pane div.search-result-container div.result-line:hover { background-color: {{ selection }} !important; }
body div#global-search-pane div.search-result-container div.active { background-color: {{ selection }} !important; }
body div#global-search-pane .filepath { color: {{ muted }} !important; }
body div#global-search-pane .search-result-highlight { color: {{ primary }} !important; }
body .dragger { background-color: {{ selection }} !important; color: {{ text }} !important; }

/* ---- scroll bars */
body ::-webkit-scrollbar, body.dark ::-webkit-scrollbar { background-color: {{ background }} !important; }
body ::-webkit-scrollbar-thumb, body.dark ::-webkit-scrollbar-thumb { background-color: {{ selection }} !important; }
body ::-webkit-scrollbar-thumb:hover { background-color: {{ dim }} !important; }
body ::-webkit-scrollbar-corner { background-color: {{ background }} !important; }
body ::-webkit-scrollbar-button, body.dark ::-webkit-scrollbar-button { display: none !important; }
