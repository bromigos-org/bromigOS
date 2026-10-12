"""Shared keyboard behavior and dialogs for the Media and Lab terminal apps."""
from textual import on
from textual.app import App
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static


class Dialog(ModalScreen):
    """Keep navigation inside a dialog, preserving normal text and select controls."""

    BINDINGS = [
        Binding("escape", "back_or_cancel", "Cancel", priority=True),
        Binding("ctrl+c", "cancel_dialog", "Cancel", priority=True, show=False),
        Binding("left,h", "button_step(-1)", "Previous choice", priority=True, show=False),
        Binding("right,l", "button_step(1)", "Next choice", priority=True, show=False),
        Binding("up", "field_step(-1)", "Previous field", priority=True, show=False),
        Binding("down", "field_step(1)", "Next field", priority=True, show=False),
        Binding("k", "choice_step(-1)", "Previous choice", priority=True, show=False),
        Binding("j", "choice_step(1)", "Next choice", priority=True, show=False),
        Binding("enter", "activate", "Choose", priority=True, show=False),
    ]
    DEFAULT_CSS = """
    Dialog { align: center middle; }
    Dialog > Vertical, Dialog > VerticalScroll {
        width: 90%; max-width: 94; height: auto; max-height: 90%;
        border: round $primary; background: $surface; padding: 1 2; overflow-y: auto;
    }
    Dialog Horizontal { height: auto; margin-top: 1; }
    Dialog Button { min-width: 12; margin-right: 1; }
    Dialog Button:focus { text-style: bold; border: tall $accent; }
    Dialog .dialog-keys { color: $text-muted; margin-top: 1; height: auto; }
    """

    def _control(self):
        widget = self.focused
        while widget is not None and widget is not self:
            if isinstance(widget, (Button, Checkbox, Input, Select)):
                return widget
            widget = widget.parent
        return None

    def check_action(self, action, parameters):
        control = self._control()
        if action in ("button_step", "activate", "choice_step"):
            return isinstance(control, (Button, Checkbox))
        if action == "field_step":
            return isinstance(control, (Button, Checkbox, Input))
        return True

    def action_back_or_cancel(self):
        control = self._control()
        if isinstance(control, Select) and control.expanded:
            control.expanded = False
            return
        self.action_cancel_dialog()

    def action_cancel_dialog(self):
        self.dismiss(None)

    def action_button_step(self, step):
        control = self._control()
        buttons = [b for b in self.query(Button) if not b.disabled and b.display]
        # Horizontal navigation stays in the current action row.
        siblings = [b for b in buttons if b.parent is getattr(control, "parent", None)]
        buttons = siblings or buttons
        if buttons:
            index = buttons.index(control) if control in buttons else 0
            buttons[(index + step) % len(buttons)].focus()

    def action_field_step(self, step):
        self.focus_previous() if step < 0 else self.focus_next()

    def action_choice_step(self, step):
        self.action_field_step(step)

    def action_activate(self):
        control = self._control()
        if isinstance(control, Button):
            control.press()
        elif isinstance(control, Checkbox) and not control.disabled:
            control.toggle()


class HelpDialog(Dialog):
    AUTO_FOCUS = "#help-close"
    DEFAULT_CSS = """
    #tui-help-box { height: 85%; }
    #tui-help-scroll { height: 1fr; }
    #tui-help-box > Button { margin-top: 1; }
    """

    def __init__(self, title, sections):
        super().__init__()
        self.title_, self.sections = title, sections

    def compose(self):
        with Vertical(id="tui-help-box"):
            yield Label(self.title_, classes="title", markup=False)
            with VerticalScroll(id="tui-help-scroll"):
                yield Static("Arrows / hjkl move · Tab / Shift+Tab change focus · [ / ] change tab\n"
                             "Enter opens or chooses · ? help · Escape returns\n"
                             "Dialogs: Tab visits fields, arrows choose buttons, Enter selects, Escape / Ctrl+C cancels.\n"
                             "Typing fields keep their normal text keys.", markup=False)
                for title, text in self.sections:
                    yield Label(title, classes="title", markup=False)
                    yield Static(text, markup=False)
            yield Button("Close help", id="help-close")

    @on(Button.Pressed, "#help-close")
    def close_help(self):
        self.dismiss(None)


class UXApp(App):
    """Prevent app shortcuts from acting behind modal forms and confirmations."""

    HELP = ()

    def check_action(self, action, parameters):
        if action in ("focus_next", "focus_previous"):
            return True
        if isinstance(self.screen, ModalScreen):
            return False
        if isinstance(self.focused, Input):
            return action == "interrupt"
        return True

    def action_help(self):
        self.push_screen(HelpDialog(f"{self.TITLE} · keyboard help", self.HELP))

    def action_interrupt(self):
        self.exit()
