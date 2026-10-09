"""`bromigos lab`'s dashboard on the tests' recorded lab (lab.sh runs it in a picture's terminal)."""
import test_lab_tui as T
from bromigos_homelab import tui

app = tui.LabApp(source=T.Fixture(), clock=lambda: T.T0, interval=3600)
app.run()
