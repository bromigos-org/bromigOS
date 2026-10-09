# The AUR helper (docs/aur.md): bromigOS's build of paru, from its own repository, on machines
# installed before it shipped, as `bromigos install` installs it now. Not where the AUR is
# off (`bromigos aur off`, setup's "off", `bromigos install --no-aur`): such a machine stays
# without it. Not where a helper is here already (paru or yay of your own): `bromigos update`
# uses that one as it is. sudo asks on the terminal, like the update's other root steps;
# pacman doesn't (--yes). Not installed yet (paru isn't in the synced repositories, or pacman
# failed): the next update tries again.
set -u
if bromigos aur ensure --yes; then
    exit 0
fi
echo "paru isn't installed yet: the next bromigos update tries again (or now: bromigos aur on)" >&2
exit 75
