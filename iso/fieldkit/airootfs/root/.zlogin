# bromigOS Field Kit (docs/fieldkit.md): the first console goes straight into the menu; when
# someone leaves it, a shell, then the menu again (fieldkit-engine console). SSH and the other
# consoles get a plain shell.
# BROMIGOS_FIELDKIT_CONSOLE: the shell the menu opens is a login shell on tty1 too; it stays a shell
if [[ -z $SSH_CONNECTION && -z ${BROMIGOS_FIELDKIT_CONSOLE:-} && ( ${BROMIGOS_CONSOLE:-} == tty1 || $(tty) == /dev/tty1 ) ]]; then
    export BROMIGOS_FIELDKIT_CONSOLE=1
    # the menu's "Install bromigOS Server": the text installer first, in this console (the
    # serial console's comes from bromigos-iso-text-check.service), then the menu
    if grep -qw bromigos.install /proc/cmdline && [[ ! -e /run/bromigos-fieldkit/installer-ran ]]; then
        mkdir -p /run/bromigos-fieldkit && : > /run/bromigos-fieldkit/installer-ran
        /usr/local/bin/bromigos-iso-install --text
    fi
    exec /usr/lib/bromigos/fieldkit/fieldkit-engine console
fi
