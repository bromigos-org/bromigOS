/* Firefox / LibreWolf chrome colours: theme "{{ theme }}" ({{ meta.name }}), written by
   `bromigos theme set`. Don't edit. The theme-set hook links it to <profile>/chrome/userChrome.css
   where a profile has a chrome/ folder (user.js needs
   toolkit.legacyUserProfileCustomizations.stylesheets = true); the browser reads it at start. */
:root {
  --bromigos-background: {{ background }};
  --bromigos-panel: {{ panel }};
  --bromigos-selection: {{ selection }};
  --bromigos-primary: {{ primary }};
  --bromigos-soft: {{ soft }};
  --bromigos-dim: {{ dim }};
  --bromigos-text: {{ text }};
  --bromigos-muted: {{ muted }};
  --bromigos-warn: {{ warn }};
  --bromigos-danger: {{ danger }};

  --lwt-accent-color: {{ panel }} !important;
  --lwt-text-color: {{ text }} !important;
  --toolbar-bgcolor: {{ panel }} !important;
  --toolbar-color: {{ text }} !important;
  --toolbarbutton-icon-fill: {{ soft }} !important;
  --toolbarbutton-hover-background: {{ selection }} !important;
  --toolbarbutton-active-background: {{ selection }} !important;
  --tab-selected-bgcolor: {{ background }} !important;
  --tab-selected-textcolor: {{ primary }} !important;
  --lwt-tab-text: {{ muted }} !important;
  --toolbox-textcolor: {{ text }} !important;
  --urlbar-box-bgcolor: {{ background }} !important;
  --urlbar-box-hover-bgcolor: {{ selection }} !important;
  --urlbar-box-active-bgcolor: {{ selection }} !important;
  --urlbar-box-text-color: {{ text }} !important;
  --toolbar-field-background-color: {{ background }} !important;
  --toolbar-field-color: {{ text }} !important;
  --toolbar-field-focus-background-color: {{ background }} !important;
  --toolbar-field-focus-color: {{ text }} !important;
  --toolbar-field-focus-border-color: {{ primary }} !important;
  --arrowpanel-background: {{ panel }} !important;
  --arrowpanel-color: {{ text }} !important;
  --arrowpanel-border-color: {{ dim }} !important;
  --panel-separator-color: {{ selection }} !important;
  --button-bgcolor: {{ selection }} !important;
  --button-hover-bgcolor: {{ dim }} !important;
  --button-primary-bgcolor: {{ primary }} !important;
  --button-primary-color: {{ background }} !important;
  --focus-outline-color: {{ primary }} !important;
  --chrome-content-separator-color: {{ selection }} !important;
  --tabs-border-color: {{ selection }} !important;
  --attention-dot-color: {{ warn }} !important;
}
#navigator-toolbox, #TabsToolbar, #nav-bar, #PersonalToolbar { background-color: {{ panel }} !important; }
#urlbar-background { border-color: {{ selection }} !important; }
.tab-background[selected] { box-shadow: inset 0 -2px 0 {{ primary }} !important; }
#sidebar-box, #sidebar-header { background-color: {{ background }} !important; color: {{ text }} !important; }
