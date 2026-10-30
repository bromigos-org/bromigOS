# bromigOS Server

bromigOS Server is bromigOS without a desktop, for servers and the machines in your lab.
It starts to a text console in bromigOS's colours. You look after it over SSH, or from
that console.

It has everything in bromigOS that doesn't need a screen: the `bromigos` command, the lab
console, the terminal apps, and [Field Kit](fieldkit.md)'s repairs. It adds:

- **SSH with keys only**, if you turn it on during the install.
- **A firewall** that lets in SSH and your lab's monitoring, and nothing else.
- **Automatic updates that undo themselves.** Each one takes a snapshot first. If the
  server doesn't come back healthy, the update is rolled back by itself.
- **Containers** with Podman. The `docker` command works too.
- **Your lab's monitoring** and its cluster.

## Install it

Start [Field Kit](fieldkit.md) from its USB stick and choose **Install › bromigOS Server (no
desktop)**. Nothing is downloaded.

## Look after it

```bash
bromigos server status        # SSH, the firewall, the last update and whether it was healthy
bromigos server update --now  # update now (it still checks and rolls back by itself)
sudo bromigos server firewall allow web   # let in a web server (ports 80 and 443)
bromigos update --rollback    # undo the last update yourself
```

If it won't start, choose **bromigOS Field Kit** in the boot menu. The contributor notes
are in [docs/server.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/server.md).
