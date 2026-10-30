// bromigos-hover: a waybar CFFI module that gives another module a hover popup
// (package bromigos-bar-hover, /usr/lib/bromigos/waybar/bromigos-hover.so; docs/desktop.md,
// "Hover popups on the bar").
//
// waybar has no hover action. This module draws nothing. It finds the module named by
// "target" in its own bar (the label waybar names "pulseaudio", say) and watches the
// pointer over it:
//
//   - the pointer rests on the target for "open-delay" ms: the popup app is asked to show
//     itself under the target, by its D-Bus action "hover" (the target's centre, in the
//     screen's logical pixels, as an int32). If the app isn't running, "command" is run
//     with "hover X" added;
//   - the pointer leaves the target: the app gets "leave" (the app closes itself a moment
//     later, unless the pointer is over the popup).
//
// Config (waybar passes each value as JSON):
//   "cffi/sound-hover": {
//     "module_path": "/usr/lib/bromigos/waybar/bromigos-hover.so",
//     "target": "pulseaudio",                   // the module's widget name
//     "app": "org.bromigos.SoundPopup",         // the GApplication id answering hover and leave
//     "command": "bromigos sound popup",        // starts it when it isn't running
//     "open-delay": 350                         // ms
//   }
#include <stdlib.h>
#include <string.h>

#include "waybar_cffi_module.h"

const size_t wbcffi_version = 2;

// BROMIGOS_HOVER_DEBUG=1: what it finds and sends, on waybar's stderr
#define SAY(...)                                    \
    do {                                            \
        if (g_getenv("BROMIGOS_HOVER_DEBUG")) {     \
            g_printerr("bromigos-hover: " __VA_ARGS__); \
            g_printerr("\n");                       \
        }                                           \
    } while (0)

typedef struct {
    GtkWidget *root;      // our own (empty) widget in the bar
    GtkWidget *target;    // the watched module's event box
    char *target_name, *app, *path, *command;
    guint delay_ms, timer, finder;
    gboolean opened;
    gulong h_enter, h_leave;
} Hover;

// a JSON string value ("\"pulseaudio\"") as plain text; a number or anything else as it is
static char *unquote(const char *raw) {
    // waybar's JSON may end in a newline
    g_autofree char *json = g_strstrip(g_strdup(raw));
    size_t n = strlen(json);
    if (n >= 2 && json[0] == '"' && json[n - 1] == '"') {
        GString *s = g_string_sized_new(n);
        for (size_t i = 1; i + 1 < n; i++) {
            if (json[i] == '\\' && i + 2 < n) {
                i++;
            }
            g_string_append_c(s, json[i]);
        }
        return g_string_free(s, FALSE);
    }
    return g_strdup(json);
}

// "org.bromigos.SoundPopup" -> "/org/bromigos/SoundPopup", as GApplication exports it
static char *object_path(const char *app) {
    char *p = g_strconcat("/", app, NULL);
    for (char *c = p; *c; c++) {
        if (*c == '.') {
            *c = '/';
        } else if (*c == '-') {
            *c = '_';
        }
    }
    return p;
}

static void spawn(Hover *h, const char *verb, int x) {
    if (!h->command || !*h->command) {
        return;
    }
    gint argc = 0;
    gchar **argv = NULL;
    if (!g_shell_parse_argv(h->command, &argc, &argv, NULL)) {
        return;
    }
    GPtrArray *a = g_ptr_array_new_with_free_func(g_free);
    for (gint i = 0; i < argc; i++) {
        g_ptr_array_add(a, g_strdup(argv[i]));
    }
    g_ptr_array_add(a, g_strdup(verb));
    if (x >= 0) {
        g_ptr_array_add(a, g_strdup_printf("%d", x));
    }
    g_ptr_array_add(a, NULL);
    g_spawn_async(NULL, (gchar **)a->pdata, NULL, G_SPAWN_SEARCH_PATH, NULL, NULL, NULL, NULL);
    g_ptr_array_free(a, TRUE);
    g_strfreev(argv);
}

typedef struct {
    Hover *h;
    int x;
    char *verb;
} Pending;

static void activated(GObject *src, GAsyncResult *res, gpointer data) {
    Pending *p = data;
    GError *err = NULL;
    GVariant *r = g_dbus_connection_call_finish(G_DBUS_CONNECTION(src), res, &err);
    if (r) {
        g_variant_unref(r);
    } else {
        // not running (no such name): start it; a leave needs nothing then
        if (g_strcmp0(p->verb, "hover") == 0) {
            spawn(p->h, p->verb, p->x);
        }
        g_error_free(err);
    }
    g_free(p->verb);
    g_free(p);
}

// the app's action, over the session bus: Activate(verb, [x], {})
static void tell(Hover *h, const char *verb, int x) {
    SAY("%s %d -> %s", verb, x, h->app);
    GDBusConnection *bus = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, NULL);
    if (!bus) {
        if (g_strcmp0(verb, "hover") == 0) {
            spawn(h, verb, x);
        }
        return;
    }
    GVariantBuilder params;
    g_variant_builder_init(&params, G_VARIANT_TYPE("av"));
    if (x >= 0) {
        g_variant_builder_add(&params, "v", g_variant_new_int32(x));
    }
    Pending *p = g_new0(Pending, 1);
    p->h = h;
    p->x = x;
    p->verb = g_strdup(verb);
    g_dbus_connection_call(bus, h->app, h->path, "org.gtk.Actions", "Activate",
                           g_variant_new("(sava{sv})", verb, &params, NULL), NULL,
                           G_DBUS_CALL_FLAGS_NO_AUTO_START, 2000, NULL, activated, p);
    g_object_unref(bus);
}

// the target's centre on the screen, in logical pixels (the bar spans its monitor)
static int centre_x(Hover *h) {
    GtkWidget *top = gtk_widget_get_toplevel(h->target);
    int x = 0, y = 0;
    GtkAllocation a;
    gtk_widget_get_allocation(h->target, &a);
    gtk_widget_translate_coordinates(h->target, top, a.width / 2, 0, &x, &y);
    GdkWindow *w = gtk_widget_get_window(top);
    if (w) {
        GdkMonitor *m = gdk_display_get_monitor_at_window(gdk_window_get_display(w), w);
        if (m) {
            GdkRectangle g;
            gdk_monitor_get_geometry(m, &g);
            x += g.x;
        }
    }
    return x;
}

static gboolean opened(gpointer data) {
    Hover *h = data;
    h->timer = 0;
    h->opened = TRUE;
    tell(h, "hover", centre_x(h));
    return G_SOURCE_REMOVE;
}

static gboolean on_enter(GtkWidget *w, GdkEventCrossing *e, gpointer data) {
    Hover *h = data;
    SAY("enter (detail %d)", e->detail);
    if (e->detail == GDK_NOTIFY_INFERIOR) {
        return FALSE;
    }
    if (!h->timer && !h->opened) {
        h->timer = g_timeout_add(h->delay_ms, opened, h);
    }
    return FALSE;
}

static gboolean on_leave(GtkWidget *w, GdkEventCrossing *e, gpointer data) {
    Hover *h = data;
    if (e->detail == GDK_NOTIFY_INFERIOR) {
        return FALSE;
    }
    if (h->timer) {
        g_source_remove(h->timer);
        h->timer = 0;
    }
    if (h->opened) {
        h->opened = FALSE;
        tell(h, "leave", -1);
    }
    return FALSE;
}

static GtkWidget *find(GtkWidget *w, const char *name) {
    if (g_strcmp0(gtk_widget_get_name(w), name) == 0) {
        return w;
    }
    if (!GTK_IS_CONTAINER(w)) {
        return NULL;
    }
    GList *kids = gtk_container_get_children(GTK_CONTAINER(w));
    GtkWidget *got = NULL;
    for (GList *k = kids; k && !got; k = k->next) {
        got = find(k->data, name);
    }
    g_list_free(kids);
    return got;
}

// the module's widgets exist once the bar is built: look for the target until it's there
static gboolean look(gpointer data) {
    Hover *h = data;
    GtkWidget *top = gtk_widget_get_toplevel(h->root);
    GtkWidget *t = gtk_widget_is_toplevel(top) ? find(top, h->target_name) : NULL;
    if (!t) {
        return G_SOURCE_CONTINUE;
    }
    // the events arrive at the module's event box (the label's parent)
    while (t && !GTK_IS_EVENT_BOX(t)) {
        t = gtk_widget_get_parent(t);
    }
    if (!t) {
        return G_SOURCE_CONTINUE;
    }
    h->target = t;
    SAY("watching %s", h->target_name);
    gtk_widget_add_events(t, GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK);
    h->h_enter = g_signal_connect(t, "enter-notify-event", G_CALLBACK(on_enter), h);
    h->h_leave = g_signal_connect(t, "leave-notify-event", G_CALLBACK(on_leave), h);
    h->finder = 0;
    return G_SOURCE_REMOVE;
}

void *wbcffi_init(const wbcffi_init_info *info, const wbcffi_config_entry *cfg, size_t n) {
    Hover *h = g_new0(Hover, 1);
    h->delay_ms = 350;
    for (size_t i = 0; i < n; i++) {
        char *v = unquote(cfg[i].value);
        SAY("config %s = %s", cfg[i].key, v);
        if (!strcmp(cfg[i].key, "target")) {
            h->target_name = v;
        } else if (!strcmp(cfg[i].key, "app")) {
            h->app = v;
        } else if (!strcmp(cfg[i].key, "command")) {
            h->command = v;
        } else if (!strcmp(cfg[i].key, "open-delay")) {
            h->delay_ms = (guint)CLAMP(atoi(v), 0, 5000);
            g_free(v);
        } else {
            g_free(v);
        }
    }
    if (!h->target_name || !h->app || !g_application_id_is_valid(h->app)) {
        g_free(h->target_name);
        g_free(h->app);
        g_free(h->command);
        g_free(h);
        return NULL;
    }
    h->path = object_path(h->app);
    GtkContainer *root = info->get_root_widget(info->obj);
    h->root = GTK_WIDGET(root);
    gtk_widget_set_name(h->root, "bromigos-hover");
    h->finder = g_timeout_add(250, look, h);
    return h;
}

void wbcffi_deinit(void *instance) {
    Hover *h = instance;
    if (h->timer) {
        g_source_remove(h->timer);
    }
    if (h->finder) {
        g_source_remove(h->finder);
    }
    if (h->target) {
        g_signal_handler_disconnect(h->target, h->h_enter);
        g_signal_handler_disconnect(h->target, h->h_leave);
    }
    g_free(h->target_name);
    g_free(h->app);
    g_free(h->path);
    g_free(h->command);
    g_free(h);
}
