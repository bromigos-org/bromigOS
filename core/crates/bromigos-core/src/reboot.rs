//! Whether the computer must restart to run what an update installed: the kernel, and
//! NVIDIA's graphics driver (docs/update.md, "When the kernel or the graphics driver
//! changes").
//!
//! NVIDIA's driver comes in two halves that must be the same version. The kernel module is
//! loaded at boot (`/sys/module/nvidia/version`). The userspace libraries
//! (`libEGL_nvidia.so.<version>`, package nvidia-utils) are loaded by each program that
//! starts. An update replaces the libraries at once, but the module only at the next boot.
//! Until then, a program that starts can't use the GPU: NVIDIA's EGL refuses to start, and
//! Mesa's software renderer (llvmpipe) draws on the CPU instead. Programs already running
//! keep the libraries they loaded, and are fine.
//!
//! The kernel is the same: an update removes the running kernel's `/usr/lib/modules/<release>`,
//! so it can't load a module it hasn't loaded yet.
//!
//! [`detect`] reads files only, through [`Files`], so a fixture tree is a whole machine.
//! [`here`] reads this machine: the kernel through `BROMIGOS_FS_ROOT` (tests), and the
//! driver's files under `BROMIGOS_GPU_ROOT` when it's set (a test hook: a VM fakes a
//! mismatch with it).

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;

use serde::Serialize;

use crate::snapshot::Files;
use crate::update::Installed;

/// NVIDIA's driver: its kernel module is a different version from its libraries.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Driver {
    /// The kernel module's version, loaded now ("615.71.09").
    pub running: String,
    /// The userspace libraries' version, installed ("615.78.08").
    pub installed: String,
    /// The package that installed them, with its version, when pacman knows it
    /// ("nvidia-utils 615.78.08-1").
    pub package: Option<String>,
}

/// The kernel: the running one is no longer installed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Kernel {
    /// `uname -r` ("7.2.9-arch1-1").
    pub running: String,
    /// The kernels installed: each `/usr/lib/modules/<release>` with a kernel in it.
    pub installed: Vec<String>,
}

/// What runs older than what's installed, until the computer restarts.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Pending {
    pub driver: Option<Driver>,
    pub kernel: Option<Kernel>,
}

/// Where the libraries live (Arch's, and other layouts').
const LIB_DIRS: &[&str] = &["/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu"];

/// The libraries whose file names carry the userspace driver's full version.
const LIBS: &[&str] = &[
    "libEGL_nvidia.so.",
    "libGLX_nvidia.so.",
    "libnvidia-glcore.so.",
];

/// The packages that install them, in the order they're looked for.
const PACKAGES: &[&str] = &["nvidia-utils", "nvidia-580xx-utils", "nvidia-470xx-utils"];

/// "615.78.08", "580.95.05", "470.256.02": digits with at least one dot.
fn is_version(s: &str) -> bool {
    s.contains('.')
        && s.split('.')
            .all(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()))
}

/// A pacman version without its epoch and release: "1:615.78.08-1" is "615.78.08".
fn upstream(v: &str) -> &str {
    let v = v.split_once(':').map_or(v, |(_, r)| r);
    v.rsplit_once('-').map_or(v, |(u, _)| u)
}

fn read_trim(files: &dyn Files, p: &str) -> Option<String> {
    files
        .read(p)
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

/// The userspace driver's versions, from its libraries' file names.
pub fn userspace_versions(files: &dyn Files) -> BTreeSet<String> {
    LIB_DIRS
        .iter()
        .flat_map(|d| files.list(d))
        .filter_map(|n| {
            LIBS.iter()
                .find_map(|l| n.strip_prefix(l))
                .filter(|v| is_version(v))
                .map(str::to_string)
        })
        .collect()
}

/// NVIDIA's driver, when its loaded module and its installed libraries differ. None when
/// they match, when no NVIDIA module is loaded (another GPU, a VM), or when nothing says
/// which libraries are installed.
pub fn driver(files: &dyn Files, packages: &BTreeMap<String, Installed>) -> Option<Driver> {
    let running = read_trim(files, "/sys/module/nvidia/version")?;
    let package = PACKAGES
        .iter()
        .find_map(|p| packages.get(*p).map(|i| (*p, i.version.as_str())));
    let mut installed = userspace_versions(files);
    if installed.is_empty() {
        installed.extend(package.map(|(_, v)| upstream(v).to_string()));
    }
    if installed.is_empty() || installed.contains(&running) {
        return None;
    }
    Some(Driver {
        running,
        // the newest, when an old library was left behind
        installed: installed
            .iter()
            .max_by_key(|v| {
                v.split('.')
                    .map(|p| p.parse::<u64>().unwrap_or(0))
                    .collect::<Vec<_>>()
            })
            .cloned()
            .unwrap_or_default(),
        package: package.map(|(n, v)| format!("{n} {v}")),
    })
}

/// The kernel, when the running one isn't installed any more. A removed kernel's folder
/// can stay behind with files nobody owns (`modules.weakdep`, a DKMS build), so a kernel
/// counts as installed only with its image (`vmlinuz`) or its modules (`kernel/`) there.
/// None when the machine shows no kernels at all (a container).
pub fn kernel(files: &dyn Files) -> Option<Kernel> {
    let running = read_trim(files, "/proc/sys/kernel/osrelease")?;
    let installed: Vec<String> = files
        .list("/usr/lib/modules")
        .into_iter()
        .filter(|r| {
            files.exists(&format!("/usr/lib/modules/{r}/vmlinuz"))
                || files.exists(&format!("/usr/lib/modules/{r}/kernel"))
        })
        .collect();
    if installed.is_empty() || installed.contains(&running) {
        return None;
    }
    Some(Kernel { running, installed })
}

/// Both, from one tree.
pub fn detect(files: &dyn Files, packages: &BTreeMap<String, Installed>) -> Pending {
    Pending {
        driver: driver(files, packages),
        kernel: kernel(files),
    }
}

/// A file tree under `root`.
struct Under(PathBuf);

impl Under {
    fn path(&self, p: &str) -> PathBuf {
        self.0.join(p.trim_start_matches('/'))
    }
}

impl Files for Under {
    fn exists(&self, path: &str) -> bool {
        self.path(path).exists()
    }
    fn read(&self, path: &str) -> Option<String> {
        fs::read(self.path(path))
            .ok()
            .map(|b| String::from_utf8_lossy(&b).into_owned())
    }
    fn list(&self, dir: &str) -> Vec<String> {
        let mut names: Vec<String> = fs::read_dir(self.path(dir))
            .into_iter()
            .flatten()
            .flatten()
            .filter_map(|e| e.file_name().into_string().ok())
            .collect();
        names.sort();
        names
    }
}

/// This machine (see the module docs).
pub fn here(packages: &BTreeMap<String, Installed>) -> Pending {
    let root = crate::snapshot::RootFs;
    let driver = match std::env::var_os("BROMIGOS_GPU_ROOT").filter(|v| !v.is_empty()) {
        Some(r) => self::driver(&Under(PathBuf::from(r)), packages),
        None => self::driver(&root, packages),
    };
    Pending {
        driver,
        kernel: kernel(&root),
    }
}

impl Pending {
    /// Something waits for a restart of the computer.
    pub fn any(&self) -> bool {
        self.driver.is_some() || self.kernel.is_some()
    }

    /// Why, in a few words, for a held-back restart's reason.
    pub fn why(&self) -> String {
        match (&self.driver, &self.kernel) {
            (Some(d), _) => format!(
                "the graphics driver was updated ({} installed, {} running)",
                d.installed, d.running
            ),
            (None, Some(_)) => "the kernel was updated".to_string(),
            (None, None) => String::new(),
        }
    }

    /// The update's last line (None: nothing waits). `background_running`: the live layer
    /// runs now, on the libraries it loaded before the update.
    pub fn message(&self, background_running: bool) -> Option<String> {
        let first = match (&self.driver, &self.kernel) {
            (Some(_), None) => "The graphics driver was updated: restart the computer to use it.",
            (None, Some(_)) => "The kernel was updated: restart the computer to use it.",
            (Some(_), Some(_)) => {
                "The kernel and the graphics driver were updated: restart the computer to use them."
            }
            (None, None) => return None,
        };
        let then = if background_running {
            "Until then, the animated background keeps running as it is."
        } else {
            "Until then, the animated background stays off."
        };
        Some(format!("{first} {then}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    /// A machine as a list of files.
    struct Mem(BTreeMap<String, String>);

    impl Mem {
        fn new(files: &[(&str, &str)]) -> Mem {
            Mem(files
                .iter()
                .map(|(p, c)| (p.to_string(), c.to_string()))
                .collect())
        }
    }

    impl Files for Mem {
        fn exists(&self, path: &str) -> bool {
            let dir = format!("{}/", path.trim_end_matches('/'));
            self.0.contains_key(path) || self.0.keys().any(|k| k.starts_with(&dir))
        }
        fn read(&self, path: &str) -> Option<String> {
            self.0.get(path).cloned()
        }
        fn list(&self, dir: &str) -> Vec<String> {
            let dir = format!("{}/", dir.trim_end_matches('/'));
            let names: BTreeSet<String> = self
                .0
                .keys()
                .filter_map(|k| k.strip_prefix(&dir))
                .map(|rest| rest.split('/').next().unwrap_or(rest).to_string())
                .collect();
            names.into_iter().collect()
        }
    }

    fn pkgs(v: &[(&str, &str)]) -> BTreeMap<String, Installed> {
        v.iter()
            .map(|(n, v)| {
                (
                    n.to_string(),
                    Installed {
                        version: v.to_string(),
                        installed: 0,
                    },
                )
            })
            .collect()
    }

    /// The operator's machine on 2026-10-09 after the update: nvidia-utils 615.78.08
    /// installed, the 615.71.09 module still loaded.
    fn after_the_driver_update() -> Mem {
        Mem::new(&[
            ("/sys/module/nvidia/version", "615.71.09\n"),
            ("/usr/lib/libEGL_nvidia.so.0", ""),
            ("/usr/lib/libEGL_nvidia.so.615.78.08", ""),
            ("/usr/lib/libnvidia-glcore.so.615.78.08", ""),
            ("/usr/lib/libc.so.6", ""),
            ("/proc/sys/kernel/osrelease", "7.2.9-arch1-1\n"),
            ("/usr/lib/modules/7.2.9-arch1-1/vmlinuz", ""),
            ("/usr/lib/modules/6.10.5-arch1-1/modules.weakdep", ""),
        ])
    }

    #[test]
    fn a_driver_update_is_a_mismatch_until_the_restart() {
        let p = detect(
            &after_the_driver_update(),
            &pkgs(&[
                ("nvidia-utils", "615.78.08-1"),
                ("nvidia-open", "615.78.08-1"),
            ]),
        );
        assert_eq!(
            p.driver,
            Some(Driver {
                running: "615.71.09".into(),
                installed: "615.78.08".into(),
                package: Some("nvidia-utils 615.78.08-1".into()),
            })
        );
        assert_eq!(
            p.kernel, None,
            "a stray folder of a removed kernel isn't a kernel"
        );
        assert!(p.any());
        assert_eq!(
            p.message(false).unwrap(),
            "The graphics driver was updated: restart the computer to use it. \
             Until then, the animated background stays off."
        );
        assert!(
            p.message(true)
                .unwrap()
                .ends_with("keeps running as it is.")
        );
        assert!(p.why().contains("615.78.08 installed, 615.71.09 running"));
    }

    #[test]
    fn a_matching_driver_or_none_is_fine() {
        // after the restart: the module is the libraries' version
        let m = Mem::new(&[
            ("/sys/module/nvidia/version", "615.78.08\n"),
            ("/usr/lib/libEGL_nvidia.so.615.78.08", ""),
        ]);
        assert_eq!(driver(&m, &pkgs(&[("nvidia-utils", "615.78.08-1")])), None);
        // no NVIDIA module (an AMD or Intel GPU, a VM): Mesa has no such halves
        let m = Mem::new(&[("/usr/lib/libEGL_nvidia.so.615.78.08", "")]);
        assert_eq!(driver(&m, &pkgs(&[])), None);
        // a module, but nothing says what's installed: can't tell, so no
        let m = Mem::new(&[("/sys/module/nvidia/version", "615.78.08\n")]);
        assert_eq!(driver(&m, &pkgs(&[])), None);
        assert!(!detect(&m, &pkgs(&[])).any());
        assert_eq!(Pending::default().message(false), None);
    }

    #[test]
    fn the_package_tells_when_the_libraries_dont() {
        let m = Mem::new(&[("/sys/module/nvidia/version", "580.95.05")]);
        let d = driver(&m, &pkgs(&[("nvidia-580xx-utils", "1:580.105.08-2")])).unwrap();
        assert_eq!(d.installed, "580.105.08");
        assert_eq!(
            d.package.as_deref(),
            Some("nvidia-580xx-utils 1:580.105.08-2")
        );
        let m = Mem::new(&[("/sys/module/nvidia/version", "580.105.08")]);
        assert_eq!(
            driver(&m, &pkgs(&[("nvidia-580xx-utils", "1:580.105.08-2")])),
            None
        );
    }

    #[test]
    fn a_library_left_behind_still_matches_or_names_the_newest() {
        let m = Mem::new(&[
            ("/sys/module/nvidia/version", "615.71.09"),
            ("/usr/lib/libEGL_nvidia.so.615.71.09", ""),
            ("/usr/lib/libEGL_nvidia.so.615.78.08", ""),
        ]);
        assert_eq!(
            driver(&m, &pkgs(&[])),
            None,
            "the running version's libraries are there"
        );
        let m = Mem::new(&[
            ("/sys/module/nvidia/version", "600.1.2"),
            ("/usr/lib/libEGL_nvidia.so.615.9.1", ""),
            ("/usr/lib/libEGL_nvidia.so.615.78.08", ""),
        ]);
        assert_eq!(driver(&m, &pkgs(&[])).unwrap().installed, "615.78.08");
    }

    #[test]
    fn a_kernel_update_removes_the_running_kernel() {
        let m = Mem::new(&[
            ("/proc/sys/kernel/osrelease", "7.2.9-arch1-1\n"),
            ("/usr/lib/modules/7.2.9-arch1-1/modules.weakdep", ""),
            ("/usr/lib/modules/7.2.10-arch1-1/vmlinuz", ""),
            ("/usr/lib/modules/7.2.10-arch1-1/kernel/fs/btrfs.ko.zst", ""),
        ]);
        let p = detect(&m, &pkgs(&[]));
        assert_eq!(
            p.kernel,
            Some(Kernel {
                running: "7.2.9-arch1-1".into(),
                installed: vec!["7.2.10-arch1-1".into()],
            })
        );
        assert_eq!(p.driver, None);
        assert_eq!(
            p.message(false).unwrap(),
            "The kernel was updated: restart the computer to use it. \
             Until then, the animated background stays off."
        );
        // a second kernel installed beside the running one is no mismatch
        let m = Mem::new(&[
            ("/proc/sys/kernel/osrelease", "7.2.9-arch1-1"),
            ("/usr/lib/modules/7.2.9-arch1-1/kernel/x.ko", ""),
            ("/usr/lib/modules/6.12.50-1-lts/vmlinuz", ""),
        ]);
        assert_eq!(kernel(&m), None);
        // a container: no kernels at all
        let m = Mem::new(&[("/proc/sys/kernel/osrelease", "7.2.9-arch1-1")]);
        assert_eq!(kernel(&m), None);
    }

    #[test]
    fn both_at_once() {
        let mut m = after_the_driver_update();
        m.0.remove("/usr/lib/modules/7.2.9-arch1-1/vmlinuz");
        m.0.insert(
            "/usr/lib/modules/7.2.10-arch1-1/vmlinuz".into(),
            String::new(),
        );
        let p = detect(&m, &pkgs(&[]));
        assert!(p.driver.is_some() && p.kernel.is_some());
        assert!(p.message(true).unwrap().starts_with(
            "The kernel and the graphics driver were updated: restart the computer to use them."
        ));
    }

    #[test]
    fn versions_and_package_versions() {
        assert!(is_version("615.78.08") && is_version("470.256.02"));
        assert!(!is_version("0") && !is_version("1.") && !is_version("615.78.08.bak"));
        assert_eq!(upstream("615.78.08-1"), "615.78.08");
        assert_eq!(upstream("1:580.105.08-2"), "580.105.08");
    }

    #[test]
    fn under_a_root() {
        let d = tempfile::tempdir().unwrap();
        fs::create_dir_all(d.path().join("sys/module/nvidia")).unwrap();
        fs::create_dir_all(d.path().join("usr/lib")).unwrap();
        fs::write(d.path().join("sys/module/nvidia/version"), "615.71.09\n").unwrap();
        fs::write(d.path().join("usr/lib/libEGL_nvidia.so.615.78.08"), "").unwrap();
        let u = Under(d.path().to_path_buf());
        assert_eq!(driver(&u, &pkgs(&[])).unwrap().running, "615.71.09");
    }
}
