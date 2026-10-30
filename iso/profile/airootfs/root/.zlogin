# The full medium's Field Kit entry (bromigos.fieldkit on the kernel's command line;
# docs/fieldkit.md): the first console goes straight into the Field Kit menu. Any other start:
# nothing (root doesn't sign in on the live desktop).
if [[ -z $SSH_CONNECTION && -z ${BROMIGOS_FIELDKIT_CONSOLE:-} && $(tty) == /dev/tty1 ]] && grep -qw bromigos.fieldkit /proc/cmdline; then
    export BROMIGOS_FIELDKIT_CONSOLE=1
    exec /usr/lib/bromigos/fieldkit/fieldkit-engine console
fi
