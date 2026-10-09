# The live layer and the widgets are packaged now (bromigos-live, bromigos-widgets, under
# /usr/lib/bromigos). Their old copies in ~/.config are gone, but Python's bytecode caches
# stay behind when sources are deleted. This removes a __pycache__ whose directory has no
# Python source left, in the places the old copies lived. A user's own plugins keep theirs.
set -eu
[ -d /usr/lib/bromigos/live ] || [ -d /usr/lib/bromigos/widgets ] || {
    echo "the live layer and the widgets aren't installed as packages yet"
    exit 75
}
for dir in "$XDG_CONFIG_HOME/bromigos-live/live" "$XDG_CONFIG_HOME/bromigos/widgets"; do
    cache="$dir/__pycache__"
    [ -d "$cache" ] || continue
    if compgen -G "$dir/*.py" >/dev/null; then
        echo "kept $cache: its sources are still there"
        continue
    fi
    rm -rf -- "$cache"
    echo "removed $cache (bytecode of code that moved into the packages)"
    rmdir -- "$dir" 2>/dev/null && echo "removed the empty $dir" || true
done
